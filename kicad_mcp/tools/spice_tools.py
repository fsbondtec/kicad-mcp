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

from fastmcp import FastMCP, FastMCPApp
from prefab_ui import PrefabApp
from prefab_ui.components import (
    Column, Row, Input, Button, RadioGroup, Radio, Text, Code, H3, Muted, Label, If, Badge, Svg,
    STATE, RESULT,
)
from prefab_ui.actions.mcp import UpdateContext
from fastmcp.apps.form import CallTool, SetState

app = FastMCPApp("SpiceSimulation")



def _grow_block(project_path, schematic_path, seed_components):
    """Export the SPICE netlist and grow the block from the seeds over the parts KiCad
    exported with a value or simulation model.

    Returns: graph, sp, block
    """
    from kicad_mcp.tools.graph_tools import get_data
    from kicad_mcp.utils.block_analysis import select_block
    from kicad_mcp.utils.spice_deck import SpiceNetlistParser

    seeds = [s.strip() for s in (seed_components or "").split(",") if s.strip()]
    graph, _ = get_data(project_path, schematic_path)
    sp = SpiceNetlistParser(schematic_path)
    sp.export_spice()
    if not sp.spice:
        return graph, sp, {"success": False,
                           "error": sp.export_error or "SPICE-Export fehlgeschlagen"}
    sp.parse()
    components = [r for r, n in graph.nodes.items() if n.get("type") == "component"]
    return graph, sp, select_block(graph, seeds, sp.simulatable_refs(components))


def _select_ports(project_path, schematic_path, seed_components):
    """Grow the block from the seeds and pre-fill its ports for the UI.

    Returns (block, ports): ports carry the suggested role, default value, clarify flag
    and readable outside pins.
    """
    from kicad_mcp.utils.block_analysis import suggest_port_role

    _, _, block = _grow_block(project_path, schematic_path, seed_components)
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
                   ports: list, analysis: str = ".op", reference_net: str = "",
                   supplies: list = None):
    """Rebuild the block and assemble the isolated SPICE deck from the ports and supplies.

    Returns: deck is the SPICE text, or None with an error
    message; warnings are the block pre-checks.
    """
    from kicad_mcp.utils.block_analysis import block_warnings
    from kicad_mcp.utils.block_analysis import reference_net as find_reference_net
    from kicad_mcp.utils.spice_deck import build_isolated_deck, build_net_node_map, node_count

    # the ports come from the UI, only the block itself is rebuilt
    graph, sp, block = _grow_block(project_path, schematic_path, seed_components)
    if not block.get("success"):
        return None, f"Fehler: {block['error']}", []

    rails = block["global_nets_touched"]
    reference_net = reference_net or find_reference_net(rails)
    if rails and reference_net is None:
        return None, (
            "Fehler: kein Massenetz (GND) im Block - bitte in der UI ein Bezugsnetz waehlen."
        ), []

    supply_nodes = {s["net"]: s["value"] for s in supplies or []
                    if (s.get("value") or "").strip() and s["net"] != reference_net}

    filtered = sp.filter_block(block["block_components"])
    if not filtered["elements"]:
        return None, (
            "Fehler: keine simulierbaren Bauteile im Block gefunden. "
            "Seeds muessen Bauteile mit Wert oder Simulationsmodell sein."
        ), []

    warnings = block_warnings(block)

    # KiCad renames nets in the SPICE export ('Net-(D1-A)' -> 'Net-_D1-A_')
    net_map = build_net_node_map(graph.netlist_data["nets"], sp.elements)
    node = lambda net: net_map.get(net, net)

    block_nodes = {n for raw in filtered["elements"]
                   for n in raw.split()[1:1 + node_count(raw.split())]}
    driven = list(supply_nodes) + [p["net"] for p in ports or []
                                   if p.get("role") in ("input", "load")]
    unmapped = [net for net in driven if node(net) not in block_nodes]
    if unmapped:
        return None, (
            f"Fehler: Netz {', '.join(unmapped)} hat im SPICE-Export keinen bekannten Namen - "
            "die Quelle/Last waere mit keinem Bauteil verbunden. KiCad benennt Netze mit "
            "Sonderzeichen im Export um (z. B. 'Net-(D1-A)' -> 'Net-_D1-A_'), der neue Name "
            "laesst sich nur ueber ein R/C/L am Netz ableiten. Abhilfe: dem Netz in KiCad ein "
            "Label ohne Sonderzeichen geben."
        ), []

    deck = build_isolated_deck(
        kept_elements=filtered["elements"],
        reference_node=node(reference_net),
        supply_nodes={node(net): spec for net, spec in supply_nodes.items()},
        ports=[(node(p.get("net")), p.get("role"), p.get("value")) for p in ports or []],
        analysis=analysis or ".op",
        models=filtered["models"],
        includes=sp.includes,
        title=f".title isolated block ({'+'.join(block['block_components'])})",
    )
    return deck, None, warnings


@app.tool()
def run_simulation(project_path: str, schematic_path: str, seed_components: str,
                   ports: list, analysis: str = ".op", reference_net: str = "",
                   supplies: list = None) -> dict:
    """Backend: assemble the isolated block deck and run it through ngspice.

    supplies: [{net, value}] source spec per supply rail, e.g. 'DC 5 AC 1'.

    run_deck validates the deck first; a deck that fails is not run and the report says
    what to fix. Otherwise reports the node voltages, or the errors ngspice raised.

    Returns:
        {"report": text incl. the deck, "svg": ngspice diagram for .ac / .tran or ""}.
    """
    from kicad_mcp.utils.spice_runner import run_deck, format_result

    deck, error, warnings = _assemble_deck(
        project_path, schematic_path, seed_components, ports, analysis, reference_net,
        supplies,
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
    button feeds those ports, the supply sources and the analysis to run_simulation,
    which assembles, validates and runs the isolated deck and shows the result
    together with the deck.
    """
    from kicad_mcp.utils.block_analysis import block_warnings, guess_voltage, reference_net

    block, ports = _select_ports(project_path, schematic_path, seed_components)

    rails = block.get("global_nets_touched", [])
    needs_reference = bool(rails) and reference_net(rails) is None
    supply_rails = [r for r in rails if r != reference_net(rails)]

    with Column(gap=4) as view:
        H3("Simulation des Blocks festlegen")
        if not block.get("success"):
            Muted(f"Keine gueltigen Seeds: {block['error']}")
            return PrefabApp(state={}, view=view)

        for warning in block_warnings(block):
            Muted(f"Hinweis: {warning}")

        if not ports:
            Muted(
                f"Block {', '.join(block['block_components'])} hat keine offenen Ports - "
                "er wird nur aus den Versorgungsnetzen gespeist."
            )
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

        args_supplies = []
        if supply_rails:
            Label("Versorgung (Quelle je Netz gegen Masse, leer = keine Quelle)")
        for i, rail in enumerate(supply_rails):
            voltage = guess_voltage(rail)
            state[f"supply_{i}"] = f"DC {voltage:g}" if voltage is not None else ""
            with Row(gap=6, align="center"):
                Text(rail)
                Input(name=f"supply_{i}", placeholder="z. B. DC 5, DC 5 AC 1, PULSE(0 5 0 1m)")
            args_supplies.append({"net": rail, "value": getattr(STATE, f"supply_{i}")})

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
            "supplies": args_supplies,
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
