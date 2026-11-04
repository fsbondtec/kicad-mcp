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

import sys

from fastmcp import FastMCP, FastMCPApp
from prefab_ui import PrefabApp
from prefab_ui.components import (
    Column, Row, Grid, Input, Button, Text, Code, H3, Muted, Label, If, Else, Badge, Svg,
    Select, SelectOption, Checkbox, Separator, Card, CardHeader, CardTitle, CardContent,
    Accordion, AccordionItem, Tabs, Tab, Alert, AlertTitle, AlertDescription, ForEach,
    DataTable, DataTableColumn,
    STATE, RESULT,
)
from prefab_ui.actions.mcp import UpdateContext
from fastmcp.apps.form import CallTool, SetState

app = FastMCPApp("SpiceSimulation")

# the whole UI goes out as one tool result, the client rejects results above 1 MB
MAX_IMAGE_BYTES = 600_000


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

    Returns (graph, block, ports): ports carry the suggested role, clarify
    flag and readable outside pins.
    """
    from kicad_mcp.utils.block_analysis import suggest_port_role

    graph, _, block = _grow_block(project_path, schematic_path, seed_components)
    if not block.get("success"):
        return graph, block, []

    ports = []
    for port in block["ports"]:
        suggestion = suggest_port_role(port)
        ports.append({
            "net": port["net"],
            "role": suggestion["role"],
            "clarify": suggestion["clarify"],
            "outside_pins": [
                f"{p['component']} {p['pinfunction'] or 'Pin ' + p['pin']} "
                f"({p['electrical_type'] or 'unspecified'})"
                for p in port["pins_outside"]
            ],
        })
    return graph, block, ports


def _block_images(project_path, graph, block, ports):
    """Schematic excerpts of the block, one per sheet with block components

    Returns: list of SVG markup strings.
    """
    from collections import defaultdict
    from kicad_mcp.utils.file_utils import get_project_files, resolve_project_file
    from kicad_mcp.utils.svg_utils import (
        build_svg_map_from_project_files, plot_svg_schematic, render_block_sheet,
    )

    project_file = resolve_project_file(project_path)
    plot_svg_schematic(project_file)
    svg_map = build_svg_map_from_project_files(get_project_files(project_file))

    wires = graph.wire_graph
    sheets = defaultdict(lambda: {"parts": [], "wires": [], "markers": []})

    for ref in block["block_components"]:
        pins = wires.component_pins.get(ref)
        if pins:
            sheets[wires.component_sheets[ref]]["parts"].append(list(pins.values()))

    for number, port in enumerate(ports, start=1):
        conns = graph.netlist_data["nets"][port["net"]]
        for seg in wires.net_segments([(c["component"], c["pin"]) for c in conns]):
            sheets[seg.sheet]["wires"].append(
                {"start": graph.format_node(seg.start), "end": graph.format_node(seg.end)})

        inside = [c for c in conns if c["component"] in block["block_components"]]
        pin = wires.component_pins.get(inside[0]["component"], {}).get(inside[0]["pin"])
        if pin:
            sheet = wires.component_sheets[inside[0]["component"]]
            sheets[sheet]["markers"].append((*pin, str(number)))

    return [render_block_sheet(svg_map[sheet], **parts)
            for sheet, parts in sheets.items() if parts["parts"] and sheet in svg_map]


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


_ANALYSIS_DEFAULTS = {
    "analysis": ".op",
    "ac_sweep": "dec", "ac_points": "20", "ac_fstart": "1", "ac_fstop": "1Meg",
    "tran_step": "1u", "tran_stop": "5m", "tran_start": "", "tran_max": "", "tran_uic": False,
}

_SOURCE_FIELDS = {
    "DC": [("dc", "Spannung", "5")],
    "PULSE": [("v1", "Low", "0"), ("v2", "High", "5"), ("td", "Verzögerung", "0"),
              ("tr", "Anstieg", "1u"), ("tf", "Abfall", "1u"), ("pw", "Pulsbreite", "50u"),
              ("per", "Periode", "100u")],
    "SIN": [("vo", "Offset", "0"), ("va", "Amplitude", "1"), ("freq", "Frequenz", "1k"),
            ("sin_td", "Verzögerung", "optional")],
}
_SOURCE_KEYS = ["type", "ac"] + [key for fields in _SOURCE_FIELDS.values() for key, _, _ in fields]


def _analysis_line(a: dict) -> str:
    """Build the analysis directive from the UI fields, e.g. '.ac dec 20 1 1Meg'."""
    v = lambda key: str(a.get(key) or "").strip()
    if v("analysis") == ".ac":
        return f".ac {v('ac_sweep')} {v('ac_points')} {v('ac_fstart')} {v('ac_fstop')}"
    if v("analysis") == ".tran":
        parts = [".tran", v("tran_step"), v("tran_stop")]
        if v("tran_start") or v("tran_max"):
            parts.append(v("tran_start") or "0")
        if v("tran_max"):
            parts.append(v("tran_max"))
        if a.get("tran_uic"):
            parts.append("uic")
        return " ".join(parts)
    return ".op"


def _source_spec(source: dict) -> str:
    """Build the SPICE source text from the UI fields, e.g. 'PULSE(0 5 0 1u 1u 50u 100u) AC 1'.
    """
    v = lambda key: str(source.get(key) or "").strip()
    kind = v("type") or "DC"
    values = [v(key) for key, _, _ in _SOURCE_FIELDS[kind]]
    while values and not values[-1]:
        values.pop()

    parts = []
    if values:
        values = [value or "0" for value in values]
        parts.append(f"DC {values[0]}" if kind == "DC" else f"{kind}({' '.join(values)})")
    if v("ac"):
        parts.append(f"AC {v('ac')}")
    return " ".join(parts)


def _port_value(port: dict) -> str:
    """SPICE value of a port: source text for input, 'R 10k' for load, '' for output."""
    if port.get("role") == "input":
        return _source_spec(port.get("source") or {})
    if port.get("role") == "load":
        value = str(port.get("load_value") or "").strip()
        return f"{port.get('load_type') or 'R'} {value}" if value else ""
    return ""


def _field(label, name, placeholder=""):
    """Labelled input field."""
    with Column(gap=1):
        Label(label)
        Input(name=name, placeholder=placeholder)


def _source_fields(prefix, state, dc=""):
    """Type selection and the fields of one independent source (supply or input port).

    Returns:
        {field: STATE reference} for run_simulation, turned into text by _source_spec.
    """
    for key in _SOURCE_KEYS:
        state[f"{prefix}_{key}"] = ""
    state[f"{prefix}_type"] = "DC"
    state[f"{prefix}_dc"] = dc

    with Grid(minColumnWidth="6rem", gap=2, align="end"):
        with Column(gap=1):
            Label("Quelle")
            with Select(name=f"{prefix}_type"):
                SelectOption(value="DC", label="DC")
                SelectOption(value="PULSE", label="PULSE")
                SelectOption(value="SIN", label="SIN")
        for kind, fields in _SOURCE_FIELDS.items():
            with If(f"{prefix}_type == '{kind}'"):
                for key, label, placeholder in fields:
                    _field(label, f"{prefix}_{key}", placeholder)
        _field("AC-Amplitude", f"{prefix}_ac", "nur für .ac")

    return {key: getattr(STATE, f"{prefix}_{key}") for key in _SOURCE_KEYS}


_RESULT_KEYS = ["status", "summary", "analysis", "voltages", "currents", "errors", "warnings",
                "deck", "svg"]

_VOLTAGE_COLUMNS = {
    "op": [("name", "Knoten"), ("value", "Spannung")],
    "tran": [("name", "Knoten"), ("min", "min"), ("max", "max"), ("end", "Ende")],
    "ac": [("name", "Knoten"), ("corner", "-3 dB bei"), ("gain", "Betrag (fstop)"),
           ("phase", "Phase (fstop)")],
}
_CURRENT_COLUMNS = {
    "op": [("name", "Bauteil"), ("value", "Strom")],
    "tran": [("name", "Bauteil"), ("max", "I max"), ("eff", "I eff")],
}


def _table(columns, rows_key):
    """DataTable over the rows in the UI state key."""
    DataTable(columns=[DataTableColumn(key=key, header=header, sortable=True)
                       for key, header in columns],
              rows=f"{{{{ {rows_key} }}}}")


def _result_view():
    """Status, errors, warnings and the voltage / current tables of the last run."""
    with Column(gap=3):
        with If("sim_status == 'ok'"):
            with Alert(variant="success", icon="circle-check"):
                AlertTitle(STATE.sim_summary)
        with Else():
            with Alert(variant="destructive", icon="circle-alert"):
                AlertTitle(STATE.sim_summary)
                with ForEach("sim_errors") as error:
                    AlertDescription(error)

        with If(STATE.sim_warnings.length() > 0):
            with Alert(variant="warning", icon="triangle-alert"):
                AlertTitle("Warnungen")
                with ForEach("sim_warnings") as warning:
                    AlertDescription(warning)

        with If(STATE.sim_voltages.length() > 0):
            Label("Spannungen")
            for analysis, columns in _VOLTAGE_COLUMNS.items():
                with If(f"sim_analysis == '{analysis}'"):
                    _table(columns, "sim_voltages")

        with If(STATE.sim_currents.length() > 0):
            Label("Ströme")
            Muted("positiv = in den Anschluss hinein; negativer Quellenstrom = Quelle liefert")
            for analysis, columns in _CURRENT_COLUMNS.items():
                with If(f"sim_analysis == '{analysis}'"):
                    _table(columns, "sim_currents")


@app.tool()
def run_simulation(project_path: str, schematic_path: str, seed_components: str,
                   ports: list, analysis: dict, reference_net: str = "",
                   supplies: list = None) -> dict:
    """Backend: assemble the isolated block deck and run it through ngspice.

    ports: [{net, role, source, load_type, load_value}] from the UI.
    analysis: the UI analysis fields, turned into the directive.
    supplies: [{net, source}] source fields per supply rail.

    run_deck validates the deck first; a deck that fails is not run and the report says
    what to fix. Otherwise reports the node voltages, or the errors ngspice raised.

    Returns:
        the result_tables() fields for the UI (status, summary, voltages, currents,
        errors, warnings) plus "analysis", "deck", "svg" (ngspice diagram for .ac / .tran
        or "") and "context" (text report + deck for the model).
    """
    from kicad_mcp.utils.spice_runner import run_deck, format_result, result_tables

    ports = [{"net": p["net"], "role": p.get("role"), "value": _port_value(p)} for p in ports or []]
    supplies = [{"net": s["net"], "value": _source_spec(s.get("source") or {})}
                for s in supplies or []]

    deck, error, warnings = _assemble_deck(
        project_path, schematic_path, seed_components, ports, _analysis_line(analysis),
        reference_net, supplies,
    )
    if error:
        return {"status": "invalid", "summary": error, "voltages": [], "currents": [],
                "errors": [], "warnings": [], "analysis": "", "deck": "", "svg": "",
                "context": error}

    result = run_deck(deck)
    result["warnings"] = warnings + result["warnings"]
    report = format_result(result)
    return {**result_tables(result, deck), "analysis": result["analysis"] or "", "deck": deck,
            "svg": result["svg"] or "", "context": f"{report}\n\n--- Deck ---\n{deck}"}


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

    graph, block, ports = _select_ports(project_path, schematic_path, seed_components)

    rails = block.get("global_nets_touched", [])
    needs_reference = bool(rails) and reference_net(rails) is None
    supply_rails = [r for r in rails if r != reference_net(rails)]

    with Column(gap=4) as view:
        H3("Simulation des Blocks festlegen")
        if not block.get("success"):
            Muted(f"Keine gueltigen Seeds: {block['error']}")
            return PrefabApp(state={}, view=view)

        state = {"sim_status": "", "sim_summary": "", "sim_analysis": "", "sim_deck": "",
                 "sim_svg": "", "sim_voltages": [], "sim_currents": [], "sim_errors": [],
                 "sim_warnings": [], "reference_net": "",
                 **_ANALYSIS_DEFAULTS}

        hints = [f"Hinweis: {warning}" for warning in block_warnings(block)]
        unclear = [p["net"] for p in ports if p["clarify"]]
        if unclear:
            hints.append(f"Rolle unklar (vorbelegt als output) - bitte pruefen: {', '.join(unclear)}")
        if not ports:
            hints.append("Keine offenen Ports - der Block wird nur aus den Versorgungsnetzen gespeist.")
        hints += [
            "Jeder Port ist ein Netz, das den Block verlaesst. Lege je Port fest, was dort "
            "angeschlossen wird",
            "Quellen: DC fuer .op, AC-Amplitude fuer .ac, PULSE/SIN fuer .tran.",
            "SPICE-Einheiten: k, Meg, m, u, n",
        ]

        with Card():
            with CardHeader():
                CardTitle(f"Block {', '.join(block['block_components'])}")
            with CardContent():
                try:
                    images = _block_images(project_path, graph, block, ports)
                except Exception as e:
                    print(f"Schaltplanausschnitt fehlgeschlagen: {e}", file=sys.stderr)
                    images = []
                shown = 0
                for image in images:
                    if shown + len(image) > MAX_IMAGE_BYTES:
                        Muted("Weitere Schaltplanausschnitte ausgelassen, zu gross fuer die Anzeige.")
                        break
                    Svg(image, width="100%")
                    shown += len(image)
                if not images:
                    Muted("Schaltplanausschnitt nicht verfuegbar.")
                with Accordion(collapsible=True):
                    with AccordionItem(title=f"Hinweise ({len(hints)})"):
                        for hint in hints:
                            Muted(hint)

        args_supplies = []
        if needs_reference or supply_rails:
            with Card():
                with CardHeader():
                    CardTitle("Versorgung")
                with CardContent():
                    with Column(gap=3):
                        if needs_reference:
                            with Row(gap=3, align="center"):
                                Label("Masse (Knoten 0)")
                                with Select(name="reference_net", placeholder="Bezugsnetz waehlen"):
                                    for rail in rails:
                                        SelectOption(value=rail, label=rail)
                        for i, rail in enumerate(supply_rails):
                            voltage = guess_voltage(rail)
                            quoted = rail.replace("\\", "\\\\").replace("'", "\\'")
                            with If(f"reference_net != '{quoted}'"):
                                Text(rail)
                                source = _source_fields(f"supply_{i}", state,
                                                        f"{voltage:g}" if voltage is not None else "")
                            args_supplies.append({"net": rail, "source": source})
                        if supply_rails:
                            Muted("Spannung leer lassen = keine Quelle an diesem Netz.")

        args_ports = []
        if ports:
            with Card():
                with CardHeader():
                    CardTitle("Ports")
                with CardContent():
                    with Column(gap=3):
                        for i, p in enumerate(ports):
                            if i:
                                Separator()
                            state[f"role_{i}"] = p["role"]
                            state[f"load_type_{i}"] = "R"
                            state[f"load_value_{i}"] = ""

                            with Row(gap=3, align="center"):
                                Text(f"{i + 1}: {p['net']}")    
                                if p["clarify"]:
                                    Badge("Rolle unklar", variant="warning")
                                with Select(name=f"role_{i}"):
                                    SelectOption(value="input", label="input - Quelle")
                                    SelectOption(value="output", label="output - wird gemessen")
                                    SelectOption(value="load", label="load - Last gegen Masse")
                            Muted(f"Aussen: {', '.join(p['outside_pins'])}")

                            with If(f"role_{i} == 'input'"):
                                source = _source_fields(f"port_{i}", state, "5")
                            with If(f"role_{i} == 'load'"):
                                with Grid(minColumnWidth="6rem", gap=2, align="end"):
                                    with Column(gap=1):
                                        Label("Last")
                                        with Select(name=f"load_type_{i}"):
                                            SelectOption(value="R", label="R")
                                            SelectOption(value="C", label="C")
                                            SelectOption(value="L", label="L")
                                    _field("Wert", f"load_value_{i}", "10k")

                            args_ports.append({
                                "net": p["net"],
                                "role": getattr(STATE, f"role_{i}"),
                                "source": source,
                                "load_type": getattr(STATE, f"load_type_{i}"),
                                "load_value": getattr(STATE, f"load_value_{i}"),
                            })

        with Card():
            with CardHeader():
                CardTitle("Analyse")
            with CardContent():
                with Column(gap=3):
                    with Select(name="analysis"):
                        SelectOption(value=".op", label="Arbeitspunkt (.op)")
                        SelectOption(value=".ac", label="Frequenzgang (.ac) - braucht AC-Amplitude")
                        SelectOption(value=".tran", label="Zeitverlauf (.tran)")
                    with If("analysis == '.ac'"):
                        with Grid(columns=4, gap=2, align="end"):
                            with Column(gap=1):
                                Label("Verlauf")
                                with Select(name="ac_sweep"):
                                    SelectOption(value="dec", label="dec - pro Dekade")
                                    SelectOption(value="oct", label="oct - pro Oktave")
                                    SelectOption(value="lin", label="lin - gesamt")
                            _field("Punkte", "ac_points", "20")
                            _field("Startfrequenz", "ac_fstart", "1")
                            _field("Stoppfrequenz", "ac_fstop", "1Meg")
                    with If("analysis == '.tran'"):
                        with Grid(columns=4, gap=2, align="end"):
                            _field("Schrittweite", "tran_step", "1u")
                            _field("Endzeit", "tran_stop", "5m")
                            _field("Startzeit", "tran_start", "optional")
                            _field("Max. Schritt", "tran_max", "optional")
                        Checkbox(name="tran_uic",
                                 label="Einschalten simulieren, alle C/L starten bei 0 (UIC)")

        call_args = {
            "project_path": project_path,
            "schematic_path": schematic_path,
            "seed_components": seed_components,
            "ports": args_ports,
            "analysis": {k: getattr(STATE, k) for k in _ANALYSIS_DEFAULTS},
            "reference_net": getattr(STATE, "reference_net"),
            "supplies": args_supplies,
        }

        Button(
            "Simulieren",
            onClick=CallTool(
                "run_simulation",
                arguments=call_args,
                onSuccess=[SetState(f"sim_{key}", getattr(RESULT, key)) for key in _RESULT_KEYS]
                          + [UpdateContext(content=RESULT.context)],
                onError=[SetState("sim_status", "failed"),
                         SetState("sim_summary", "Fehler beim Aufruf von run_simulation.")],
            ),
        )

        with If("sim_status"):
            with Tabs(value="result"):
                with Tab(title="Ergebnis", value="result"):
                    _result_view()
                with Tab(title="Diagramm", value="plot"):
                    with If("sim_svg"):
                        Svg(getattr(STATE, "sim_svg"), width="100%")
                    with Else():
                        Muted("Diagramm nur bei .ac und .tran.")
                with Tab(title="Deck", value="deck"):
                    Code(getattr(STATE, "sim_deck"))

    return PrefabApp(state=state, view=view)


def register_spice_tools(mcp: FastMCP) -> None:
    """Register the SPICE simulation app (port-config UI + run_simulation backend)."""
    mcp.add_provider(app)
