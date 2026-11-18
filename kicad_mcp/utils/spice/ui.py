"""
SPICE simulation UI (prefab_ui): the view of open_spice_simulation and its building
blocks (input fields, analysis card, result view, schematic excerpts of the block).
"""

import sys
from collections import defaultdict

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

from kicad_mcp.utils.file_utils import get_project_files, resolve_project_file
from kicad_mcp.utils.spice.block import block_warnings, ground_nets, guess_voltage
from kicad_mcp.utils.spice.fields import (
    ANALYSIS_DEFAULTS, ANALYSIS_FIELDS, SOURCE_FIELDS, SOURCE_KEYS,
)
from kicad_mcp.utils.svg_utils import (
    build_svg_map_from_project_files, plot_svg_schematic, render_block_sheet,
)

# the whole UI goes out as one tool result, the client rejects results above 1 MB
MAX_IMAGE_BYTES = 600_000

# result fields of run_simulation that the view copies into its state
RESULT_KEYS = ["status", "summary", "analysis", "voltages", "currents", "errors", "warnings",
               "deck", "svg"]


def field(label, name, placeholder=""):
    """Labelled input field."""
    with Column(gap=1):
        Label(label)
        Input(name=name, placeholder=placeholder)


def source_fields(prefix, state, dc="", dc_placeholder=None, ac=""):
    """Type selection and the fields of one independent source (supply or input port)

    Returns:
        {field: STATE reference} for run_simulation, turned into text by source_spec.
    """
    # PULSE / SIN start with the example values, so switching the type gives a working source
    for fields in SOURCE_FIELDS.values():
        for key, _, example in fields:
            state[f"{prefix}_{key}"] = "" if example == "optional" else example
    state[f"{prefix}_type"] = "DC"
    state[f"{prefix}_dc"] = dc
    state[f"{prefix}_ac"] = ac

    with Grid(minColumnWidth="6rem", gap=2, align="end"):
        with Column(gap=1):
            Label("Source")
            with Select(name=f"{prefix}_type"):
                for kind in SOURCE_FIELDS:
                    SelectOption(value=kind, label=kind)
        for kind, fields in SOURCE_FIELDS.items():
            with If(f"{prefix}_type == '{kind}'"):
                for key, label, placeholder in fields:
                    if key == "dc" and dc_placeholder:
                        placeholder = dc_placeholder
                    field(label, f"{prefix}_{key}", placeholder)
        with If("analysis == '.ac'"):
            field("AC amplitude", f"{prefix}_ac", "empty = no AC")

    return {key: getattr(STATE, f"{prefix}_{key}") for key in SOURCE_KEYS}


def analysis_card():
    """Analysis selection with the .ac / .tran parameter fields."""
    with Card():
        with CardHeader():
            CardTitle("Analysis")
        with CardContent():
            with Column(gap=3):
                with Select(name="analysis"):
                    SelectOption(value=".op", label="Operating point (.op)")
                    SelectOption(value=".ac", label="Frequency response (.ac) - needs an AC amplitude")
                    SelectOption(value=".tran", label="Transient (.tran)")
                with If("analysis == '.ac'"):
                    with Grid(columns=4, gap=2, align="end"):
                        with Column(gap=1):
                            Label("Sweep")
                            with Select(name="ac_sweep"):
                                SelectOption(value="dec", label="dec - per decade")
                                SelectOption(value="oct", label="oct - per octave")
                                SelectOption(value="lin", label="lin - total")
                        for key, label, example in ANALYSIS_FIELDS[".ac"]:
                            field(label, key, example)
                with If("analysis == '.tran'"):
                    with Grid(columns=4, gap=2, align="end"):
                        for key, label, example in ANALYSIS_FIELDS[".tran"]:
                            field(label, key, example)
                    Checkbox(name="tran_uic",
                             label="Simulate power-up, all C/L start at 0 (UIC)")


def supply_card(rails, grounds, state):
    """Reference net selection and one source per rail.

    Returns:
        the supplies argument of run_simulation: [{net, source}].
    """
    supplies = []
    with Card():
        with CardHeader():
            CardTitle("Supplies")
        with CardContent():
            with Column(gap=3):
                with Row(gap=3, align="center"):
                    Label("Ground (node 0)")
                    with Select(name="reference_net", placeholder="Choose reference net"):
                        for rail in rails:
                            SelectOption(value=rail, label=rail)
                for i, rail in enumerate(rails):
                    voltage = guess_voltage(rail)
                    several = len(grounds) > 1 and rail in grounds
                    hint = "0 = connected, empty = separate" if several else None
                    quoted = rail.replace("\\", "\\\\").replace("'", "\\'")
                    with If(f"reference_net != '{quoted}'"):
                        Text(rail)
                        source = source_fields(f"supply_{i}", state,
                                               f"{voltage:g}" if voltage is not None else "",
                                               dc_placeholder=hint)
                    supplies.append({"net": rail, "source": source})
                if len(rails) > 1:
                    Muted("Leave the voltage empty = no source on this net.")
    return supplies


def ports_card(ports, state):
    """Role per port with its source (input) or load (load) fields.

    Returns:
        the ports argument of run_simulation: [{net, role, source, load_type, load_value}].
    """
    port_args = []
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
                            Badge("Role unclear", variant="warning")
                        with Select(name=f"role_{i}"):
                            SelectOption(value="input", label="input - source")
                            SelectOption(value="output", label="output - measured")
                            SelectOption(value="load", label="load - load to ground")
                    Muted(f"Outside: {', '.join(p['outside_pins'])}")

                    # the If only decides what the UI shows, the fields are built for every port
                    with If(f"role_{i} == 'input'"):
                        source = source_fields(f"port_{i}", state, "5", ac="1")
                    with If(f"role_{i} == 'load'"):
                        with Grid(minColumnWidth="6rem", gap=2, align="end"):
                            with Column(gap=1):
                                Label("Load")
                                with Select(name=f"load_type_{i}"):
                                    SelectOption(value="R", label="R")
                                    SelectOption(value="C", label="C")
                                    SelectOption(value="L", label="L")
                            field("Value", f"load_value_{i}", "10k")

                    port_args.append({
                        "net": p["net"],
                        "role": getattr(STATE, f"role_{i}"),
                        "source": source,
                        "load_type": getattr(STATE, f"load_type_{i}"),
                        "load_value": getattr(STATE, f"load_value_{i}"),
                    })
    return port_args


VOLTAGE_COLUMNS = {
    "op": [("name", "Node"), ("value", "Voltage")],
    "tran": [("name", "Node"), ("min", "min"), ("max", "max"), ("end", "end")],
    "ac": [("name", "Node"), ("corner", "Pass band (-3 dB)"), ("gain", "Magnitude (fstop)"),
           ("phase", "Phase (fstop)")],
}
CURRENT_COLUMNS = {
    "op": [("name", "Component"), ("value", "Current")],
    "tran": [("name", "Component"), ("max", "I max"), ("eff", "I rms")],
}


def table(columns, rows_key):
    """DataTable over the rows in the UI state key."""
    DataTable(columns=[DataTableColumn(key=key, header=header, sortable=True)
                       for key, header in columns],
              rows=f"{{{{ {rows_key} }}}}")


def result_view():
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
                AlertTitle("Warnings")
                with ForEach("sim_warnings") as warning:
                    AlertDescription(warning)

        with If(STATE.sim_voltages.length() > 0):
            Label("Voltages")
            for analysis, columns in VOLTAGE_COLUMNS.items():
                with If(f"sim_analysis == '{analysis}'"):
                    table(columns, "sim_voltages")

        with If(STATE.sim_currents.length() > 0):
            Label("Currents")
            Muted("positive = into the terminal; negative source current = source delivers")
            for analysis, columns in CURRENT_COLUMNS.items():
                with If(f"sim_analysis == '{analysis}'"):
                    table(columns, "sim_currents")


def block_images(project_path, graph, block, ports):
    """Schematic excerpts of the block, one per sheet with block components

    Returns: list of SVG markup strings.
    """

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


def block_card(project_path, graph, block, ports):
    """Schematic excerpts of the block (limited to MAX_IMAGE_BYTES) and the hints on it."""
    
    hints = [f"Note: {warning}" for warning in block_warnings(block)]
    unclear = [p["net"] for p in ports if p["clarify"]]
    if unclear:
        hints.append(f"Role unclear (preset to output) - please check: {', '.join(unclear)}")
    if not ports:
        hints.append("No open ports - the block is fed only from the supply nets.")
    hints += [
        "Every port is a net that leaves the block. Set for each port what is connected "
        "there.",
        "Sources: DC for .op, AC amplitude for .ac, PULSE/SIN for .tran.",
        "SPICE units: k, Meg, m, u, n",
    ]

    with Card():
        with CardHeader():
            CardTitle(f"Block {', '.join(block['block_components'])}")
        with CardContent():
            try:
                images = block_images(project_path, graph, block, ports)
            except Exception as e:
                print(f"Schematic excerpt failed: {e}", file=sys.stderr)
                images = []
            shown = 0
            for image in images:
                if shown + len(image) > MAX_IMAGE_BYTES:
                    Muted("Further schematic excerpts left out, too large to display.")
                    break
                Svg(image, width="100%")
                shown += len(image)
            if not images:
                Muted("Schematic excerpt not available.")
            with Accordion(collapsible=True):
                with AccordionItem(title=f"Notes ({len(hints)})"):
                    for hint in hints:
                        Muted(hint)


def simulation_view(project_path, schematic_path, seed_components, graph, block, ports):
    """View of open_spice_simulation: block excerpt and hints, analysis, supplies and
    ports with their source / load fields, the button that calls run_simulation and the
    result tabs.

    Args:
        graph, block, ports: from select_ports.

    Returns:
        the PrefabApp with the initial state.
    """
    rails = block.get("global_nets_touched", [])
    grounds = ground_nets(rails)

    with Column(gap=4) as view:
        H3("Set up the block simulation")
        if not block.get("success"):
            Muted(f"No valid seeds: {block['error']}")
            return PrefabApp(state={}, view=view)

        state = {"sim_status": "", "sim_summary": "", "sim_analysis": "", "sim_deck": "",
                 "sim_svg": "", "sim_voltages": [], "sim_currents": [], "sim_errors": [],
                 "sim_warnings": [], "reference_net": grounds[0] if grounds else "",
                 **ANALYSIS_DEFAULTS}

        block_card(project_path, graph, block, ports)
        analysis_card()

        args_supplies = supply_card(rails, grounds, state) if rails else []
        args_ports = ports_card(ports, state) if ports else []

        call_args = {
            "project_path": project_path,
            "schematic_path": schematic_path,
            "seed_components": seed_components,
            "ports": args_ports,
            "analysis": {k: getattr(STATE, k) for k in ANALYSIS_DEFAULTS},
            "reference_net": getattr(STATE, "reference_net"),
            "supplies": args_supplies,
        }

        Button(
            "Simulate",
            onClick=CallTool(
                "run_simulation",
                arguments=call_args,
                onSuccess=[SetState(f"sim_{key}", getattr(RESULT, key)) for key in RESULT_KEYS]
                          + [UpdateContext(content=RESULT.context)],
                onError=[SetState("sim_status", "failed"),
                         SetState("sim_summary", "Error calling run_simulation.")],
            ),
        )

        with If("sim_status"):
            with Tabs(value="result"):
                with Tab(title="Result", value="result"):
                    result_view()
                with Tab(title="Diagram", value="plot"):
                    with If("sim_svg"):
                        Svg(getattr(STATE, "sim_svg"), width="100%")
                    with Else():
                        Muted("Diagram only for .ac and .tran.")
                with Tab(title="Deck", value="deck"):
                    Code(getattr(STATE, "sim_deck"))

    return PrefabApp(state=state, view=view)
