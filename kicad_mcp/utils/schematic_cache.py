"""
One cache entry per schematic for its kicad-cli exports: the KiCad netlist (as graph)
and the SPICE netlist. Both are exported again only if the schematic has changed.
"""

import sys
import threading
from typing import Dict

from kicad_mcp.utils.cli_drc import export_netlist
from kicad_mcp.utils.file_utils import hash_schematic
from kicad_mcp.utils.graph_analysis import CircuitGraph
from kicad_mcp.utils.net_parser import NetlistParser

CACHE_LOCK = threading.Lock()

_CACHE = {}

def get_entry(schematic_path: str) -> dict:
    """Cache entry of the schematic, created empty on first use."""
    entry = _CACHE.get(schematic_path)
    if entry is None:
        entry = {
            "project_path": None,
            "schematic_hash": None,
            "graph": None,
            "structured_data": None,
            "spice": None,
            "spice_schematic_hash": None,
        }
        _CACHE[schematic_path] = entry
    return entry

def get_graph_data(project_path: str, schematic_path: str,
                   schematic_hash: str = None) -> tuple[CircuitGraph, Dict]:
    """
    Get the cached circuit graph or build a new one if the schematic has changed.

    This function parses the KiCad schematic into a structured format and builds a
    logical CircuitGraph. If the schematic hasn't changed, the cached graph is
    returned immediately.

    Args:
        project_path (str): Absolute or relative path to the KiCad project directory.
        schematic_path (str): Path to the specific KiCad schematic file (.kicad_sch).
        schematic_hash (str): hash_schematic() of the schematic if the caller already has it.

    Returns:
        tuple[CircuitGraph, Dict]: A tuple containing:
            - The instantiated CircuitGraph object representing the schematic logic.
            - A dictionary containing the structured raw data parsed from the netlist.
    """
    if schematic_hash is None:
        schematic_hash = hash_schematic(schematic_path)

    with CACHE_LOCK:
        entry = get_entry(schematic_path)
        graph_is_current = (entry["schematic_hash"] == schematic_hash
                            and entry["project_path"] == project_path)
        if graph_is_current:
            return entry["graph"], entry["structured_data"]

        parser = NetlistParser(schematic_path)
        parser.export_netlist()
        structured_data = parser.structure_data()
        graph = CircuitGraph(structured_data, project_path)

        entry["graph"] = graph
        entry["structured_data"] = structured_data
        entry["project_path"] = project_path
        entry["schematic_hash"] = schematic_hash
        return graph, structured_data


def get_spice_netlist(schematic_path: str, schematic_hash: str = None):
    """Get the SPICE netlist of the schematic, exported via kicad-cli only if the
    cached one was made from an older schematic state.

    Args:
        schematic_path: root .kicad_sch file.
        schematic_hash: hash_schematic() of the schematic if the caller already has it.

    Returns:
        (spice, error): spice is the netlist text, or None with an error message.
    """
    if schematic_hash is None:
        try:
            schematic_hash = hash_schematic(schematic_path)
        except OSError as e:
            return None, f"Schaltplan nicht lesbar: {e}"

    with CACHE_LOCK:
        entry = get_entry(schematic_path)
        spice_is_current = (entry["spice"] is not None
                            and entry["spice_schematic_hash"] == schematic_hash)
        if spice_is_current:
            return entry["spice"], None

        spice, error = export_netlist(schematic_path, "spice")
        if error:
            print(error, file=sys.stderr)
            return None, error

        entry["spice"] = spice
        entry["spice_schematic_hash"] = schematic_hash
        return spice, None
