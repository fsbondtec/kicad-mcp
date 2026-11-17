"""
One cache entry per schematic for its kicad-cli exports: the KiCad netlist (as graph)
and the SPICE netlist. Both are exported again only if the schematic has changed.
"""

import os
import sys
import threading
from typing import Dict

from kicad_mcp.utils.cli_drc import export_netlist
from kicad_mcp.utils.file_utils import hash_schematic
from kicad_mcp.utils.graph_analysis import CircuitGraph
from kicad_mcp.utils.net_parser import NetlistParser

CACHE_LOCK = threading.Lock()

_CACHE = {}

def normalize_path(path: str) -> str:
    """One spelling per file (absolute, case and slashes unified on Windows), so the
    same schematic or project never gets a second cache entry."""
    return os.path.normcase(os.path.abspath(path))

def get_entry(schematic_path: str, schematic_hash: str) -> dict:
    """Cache entry of the schematic, emptied if the schematic has changed."""
    entry = _CACHE.setdefault(normalize_path(schematic_path), {})
    if entry.get("hash") != schematic_hash:
        entry.clear()
        entry["hash"] = schematic_hash
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

    Raises:
        RuntimeError: the netlist export failed; nothing is cached, the next call
            exports again.
    """
    if schematic_hash is None:
        schematic_hash = hash_schematic(schematic_path)

    project = normalize_path(project_path)
    with CACHE_LOCK:
        entry = get_entry(schematic_path, schematic_hash)
        if entry.get("project") != project:
            parser = NetlistParser(schematic_path)
            parser.export_netlist()
            structured_data = parser.structure_data()
            entry["graph"] = (CircuitGraph(structured_data, project_path), structured_data)
            entry["project"] = project
        return entry["graph"]


def get_spice_netlist(schematic_path: str, schematic_hash: str):
    """Get the SPICE netlist of the schematic, exported via kicad-cli only if the
    cached one was made from an older schematic state.

    Args:
        schematic_path: root .kicad_sch file.
        schematic_hash: hash_schematic() of the schematic.

    Returns:
        (spice, message): spice is the netlist text or None. Without spice, message is
        the error; with spice, it is what kicad-cli complained about (e.g. missing
        models) or None.
    """
    with CACHE_LOCK:
        entry = get_entry(schematic_path, schematic_hash)
        if "spice" not in entry:
            spice, error = export_netlist(schematic_path, "spice")
            if not spice:
                print(error, file=sys.stderr)
                return None, error
            entry["spice"] = (spice, error)
        return entry["spice"]
