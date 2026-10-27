"""
Interactive UI for simulating an isolated SPICE deck.

The model opens the UI by calling open_spice_simulation with the project/schematic/seeds.
select_block runs first. On submit, run_simulation reruns the pipeline, assembles the
deck (turning each port into a source / load / open), validates and runs it.

Roles:
  - input  -> a source drives the net  -> value = SPICE source spec (DC/AC/SIN/PULSE)
  - output -> the block drives it, outside only senses -> left open, measured, no value
  - load   -> the outside presents an impedance -> value = a passive (R/C/L)
"""

import threading

from fastmcp import FastMCP, FastMCPApp
from prefab_ui import PrefabApp
from prefab_ui.components import (
    Column, Row, Input, Button, RadioGroup, Radio, Text, Code, H3, Muted, Label, If, Badge, Svg,
    STATE, RESULT,
)
from prefab_ui.actions.mcp import UpdateContext
from fastmcp.apps.form import CallTool, SetState

app = FastMCPApp("SpiceSimulation")



def _select_ports(project_path, schematic_path, seed_components):
    """Grow the block from the seeds and pre-fill its ports for the UI.

    Returns (block, ports): ports carry the suggested role, default value, clarify flag
    and readable outside pins.
    """
    from kicad_mcp.tools.graph_tools import get_data
    from kicad_mcp.utils.block_analysis import select_block, suggest_port_role

    seeds = [s.strip() for s in (seed_components or "").split(",") if s.strip()]
    graph, _ = get_data(project_path, schematic_path)
    block = select_block(graph, seeds)
    if not block.get("success"):
        return block, []

    ports = []
    for port in block["ports"]:
        suggestion = suggest_port_role(port)
        ports.append({
            "net": port["net"],
            "role": suggestion["role"],
            "value": "DC 5" if suggestion["role"] == "input" else "",   # pre-filled in the UI
            "clarify": suggestion["clarify"],
            "outside_pins": [
                f"{p['component']} {p['pinfunction'] or 'Pin ' + p['pin']} "
                f"({p['electrical_type'] or 'unspecified'})"
                for p in port["pins_outside"]
            ],
        })
    return block, ports


def _assemble_deck(project_path: str, schematic_path: str, seed_components: str,
                   ports: list, analysis: str = ".op", reference_net: str = ""):
    """Rebuild the block and assemble the isolated SPICE deck from the ports.

    Returns (deck, error, warnings): deck is the SPICE text, or None with an error
    message; warnings are block pre-checks and refs missing from the export.
    """
    from kicad_mcp.tools.graph_tools import get_data
    from kicad_mcp.utils.block_analysis import block_warnings, guess_voltage, select_block
    from kicad_mcp.utils.block_analysis import reference_net as find_reference_net
    from kicad_mcp.utils.spice_deck import (
        SpiceNetlistParser, build_isolated_deck, build_net_node_map,
    )

    # the ports come from the UI, only the block itself is rebuilt
    seeds = [s.strip() for s in (seed_components or "").split(",") if s.strip()]
    graph, _ = get_data(project_path, schematic_path)
    block = select_block(graph, seeds)
    if not block.get("success"):
        return None, f"Fehler: ungueltige Seeds {block.get('missing', seed_components)}", []

    rails = block["global_nets_touched"]
    reference_net = reference_net or find_reference_net(rails)
    if rails and reference_net is None:
        return None, (
            "Fehler: kein Massenetz (GND) im Block - bitte in der UI ein Bezugsnetz waehlen."
        ), []
    
    voltages = {r: guess_voltage(r) for r in rails if r != reference_net}
    supplies = {r: v for r, v in voltages.items() if v is not None}

    sp = SpiceNetlistParser(schematic_path)
    sp.export_spice()
    if not sp.spice:
        return None, f"Fehler: {sp.export_error or 'SPICE-Export fehlgeschlagen'}", []
    sp.parse()
    filtered = sp.filter_block(block["block_components"])
    if not filtered["elements"]:
        return None, (
            "Fehler: keine simulierbaren Bauteile im Block gefunden. "
            f"Fehlende/nicht exportierte Refs: {', '.join(filtered['missing_refs']) or 'alle'}. "
            "Seeds muessen simulierbare Bauteile (R/C/L/Dioden/Subckt) sein."
        ), []

    warnings = block_warnings(block)
    if filtered["missing_refs"]:
        warnings.append(
            f"Nicht exportiert, fehlen im Deck: {', '.join(filtered['missing_refs'])}."
        )

    net_map = build_net_node_map(graph.netlist_data["nets"], sp.elements)
    deck = build_isolated_deck(
        kept_elements=filtered["elements"],
        reference_node=reference_net,
        supply_nodes=supplies,
        ports=[(net_map.get(p.get("net"), p.get("net")), p.get("role"), p.get("value"))
               for p in ports or []],
        analysis=analysis or ".op",
        models=filtered["models"],
        includes=filtered["includes"],
        title=f".title isolated block ({'+'.join(block['block_components'])})",
    )
    return deck, None, warnings


@app.tool()
def run_simulation(project_path: str, schematic_path: str, seed_components: str,
                   ports: list, analysis: str = ".op", reference_net: str = "") -> dict:
    """Backend: assemble the isolated block deck and run it through ngspice.

    run_deck validates the deck first; a deck that fails is not run and the report says
    what to fix. Otherwise reports the node voltages, or the errors ngspice raised.

    Returns:
        {"report": text incl. the deck, "svg": ngspice diagram for .ac / .tran or ""}.
    """
    from kicad_mcp.utils.spice_runner import run_deck, format_result

    deck, error, warnings = _assemble_deck(
        project_path, schematic_path, seed_components, ports, analysis, reference_net
    )
    if error:
        return {"report": error, "svg": ""}

    result = run_deck(deck)
    result["warnings"] = warnings + result["warnings"]
    return {"report": format_result(result) + "\n\n--- Deck ---\n" + deck,
            "svg": result["svg"] or ""}


@app.ui()
def open_spice_simulation(project_path: str, schematic_path: str, seed_components: str):
    """Entry point of the SPICE pipeline: open the UI for the block grown from the seeds.

    Grows the block from the seeds, detects the open ports and
    lets the user assign each one a role (source/load/open output) and value. The
    button feeds those ports to run_simulation, which assembles, validates
    and runs the isolated deck and shows the result together with the deck.

    A block without open ports has nothing to configure: it is simulated (.op) right
    away, unless a reference net still has to be chosen.
    """
    from kicad_mcp.utils.block_analysis import block_warnings, reference_net
    from kicad_mcp.utils.spice_deck import SpiceNetlistParser

    block, ports = _select_ports(project_path, schematic_path, seed_components)
    if block.get("success"):
        # start the slow SPICE export in the background while the user sets the ports,
        threading.Thread(
            target=SpiceNetlistParser(schematic_path).export_spice, daemon=True
        ).start()

    rails = block.get("global_nets_touched", [])
    needs_reference = bool(rails) and reference_net(rails) is None
    auto_run = block.get("success") and not ports and not needs_reference

    with Column(gap=4) as view:
        H3("Simulation" if auto_run else "Ports des Blocks festlegen")
        if not block.get("success"):
            Muted(f"Keine gueltigen Seeds: {block.get('missing', seed_components)}")
            return PrefabApp(state={}, view=view)

        for warning in block_warnings(block):
            Muted(f"Hinweis: {warning}")

        if not ports:
            Muted(
                f"Block {', '.join(block['block_components'])} hat keine offenen Ports - "
                "er wird nur aus den Versorgungsnetzen gespeist."
            )
            if auto_run:
                Label("Simulationsergebnis")
                Code(run_simulation(project_path, schematic_path, seed_components, [])["report"])
                return PrefabApp(state={}, view=view)
        else:
            Muted(
                "Jeder Port ist ein Netz, das den Block verlaesst. Lege je Port fest, "
                "was dort angeschlossen wird (Vorschlag ist vorbelegt)."
            )
            unclear = [p["net"] for p in ports if p["clarify"]]
            if unclear:
                Muted(
                    f"{len(unclear)} von {len(ports)} Ports mit unklarer Rolle (vorbelegt als "
                    f"output) - bitte pruefen: {', '.join(unclear)}"
                )

        state = {"sim_result": "", "sim_svg": "", "analysis": ".op", "reference_net": ""}

        if needs_reference:
            with Column(gap=1):
                Label("Bezugsnetz (Masse)")
                with RadioGroup(name="reference_net"):
                    for rail in rails:
                        Radio(option=rail, label=rail)
                Muted("Kein GND-Netz im Block - waehle das Netz, das als Knoten 0 gilt.")

        with Column(gap=1):
            Label("Analyse")
            Input(name="analysis", placeholder=".op | .ac dec 20 1 1Meg | .tran 1u 5m")
            Muted(".op = Arbeitspunkt, .ac = Frequenzgang (braucht AC-Quelle), .tran = Zeitverlauf.")
        args_ports = []
        for i, p in enumerate(ports):
            state[f"role_{i}"] = p["role"]
            state[f"value_{i}"] = p["value"]

            with Row(gap=6, align="start"):
                with Column(gap=1):
                    Label("Port (Netz)")
                    Text(p["net"])
                    if p["clarify"]:
                        Badge("Rolle unklar - bitte pruefen", variant="warning")
                    Muted(f"Aussen: {', '.join(p['outside_pins'])}")
                with Column(gap=1):
                    Label("Rolle")
                    with RadioGroup(name=f"role_{i}"):
                        Radio(option="input", label="input - Quelle treibt das Netz")
                        Radio(option="output", label="output - Ausgang, wird gemessen")
                        Radio(option="load", label="load - Impedanz/Last (R/C)")
                with Column(gap=1):
                    Label("Wert")
                    with If(f"role_{i} == 'input'"):
                        Input(name=f"value_{i}", placeholder="z. B. DC 5, AC 1, SIN(0 1 1k)")
                        Muted("SPICE-Quelle: DC fuer .op, AC fuer .ac, SIN/PULSE fuer .tran.")
                    with If(f"role_{i} == 'load'"):
                        Input(name=f"value_{i}", placeholder="z. B. R 10k, C 100p, L 1m")
                        Muted("Passive Last gegen Masse: Bauteiltyp + Wert.")
                    with If(f"role_{i} == 'output'"):
                        Muted("Ausgang - wird gemessen, keine Eingabe noetig.")

            args_ports.append({
                "net": p["net"],
                "role": getattr(STATE, f"role_{i}"),
                "value": getattr(STATE, f"value_{i}"),
            })

        call_args = {
            "project_path": project_path,
            "schematic_path": schematic_path,
            "seed_components": seed_components,
            "ports": args_ports,
            "analysis": getattr(STATE, "analysis"),
            "reference_net": getattr(STATE, "reference_net"),
        }

        Button(
            "Simulieren",
            onClick=CallTool(
                "run_simulation",
                arguments=call_args,
                onSuccess=[
                    SetState("sim_result", RESULT.report),
                    SetState("sim_svg", RESULT.svg),
                    UpdateContext(content=RESULT.report),
                ],
                onError=SetState("sim_result", "Fehler beim Aufruf von run_simulation."),
            ),
        )

        Label("Simulationsergebnis")
        Svg(getattr(STATE, "sim_svg"), width="100%")
        Code(getattr(STATE, "sim_result"))

    return PrefabApp(state=state, view=view)


def register_spice_tools(mcp: FastMCP) -> None:
    """Register the SPICE simulation app (port-config UI + run_simulation backend)."""
    mcp.add_provider(app)
