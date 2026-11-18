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

from kicad_mcp.utils.spice.deck import assemble_deck, select_ports
from kicad_mcp.utils.spice.fields import analysis_line, check_fields, port_value, source_spec
from kicad_mcp.utils.spice.runner import run_deck, format_result, result_tables
from kicad_mcp.utils.spice.ui import simulation_view

app = FastMCPApp("SpiceSimulation")


def _invalid_result(summary: str, errors: list) -> dict:
    """run_simulation result for input that cannot be simulated; ngspice did not run."""
    context = "\n".join([summary] + errors)
    return {"status": "invalid", "summary": summary, "voltages": [], "currents": [],
            "errors": errors, "warnings": [], "analysis": "", "deck": "", "svg": "",
            "context": context}


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

    if analysis.get("analysis") != ".ac":
        for item in (ports or []) + (supplies or []):
            if item.get("source"):
                item["source"] = {**item["source"], "ac": ""}

    field_errors = check_fields(analysis, ports, supplies)
    if field_errors:
        return _invalid_result("Invalid input - please correct these fields.",
                               field_errors)

    ports = [{"net": p["net"], "role": p.get("role"), "value": port_value(p),
              "load_type": p.get("load_type") or "R"} for p in ports or []]
    supplies = [{"net": s["net"], "value": source_spec(s.get("source") or {})}
                for s in supplies or []]

    deck, error, warnings = assemble_deck(
        project_path, schematic_path, seed_components, ports, analysis_line(analysis),
        reference_net, supplies,
    )
    if error:
        return _invalid_result(error, [])

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

    graph, block, ports = select_ports(project_path, schematic_path, seed_components)
    return simulation_view(project_path, schematic_path, seed_components, graph, block,
                           ports)


def register_spice_tools(mcp: FastMCP) -> None:
    """Register the SPICE simulation app (port-config UI + run_simulation backend)."""
    mcp.add_provider(app)
