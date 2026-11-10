"""
One cache entry per schematic for its kicad-cli exports: the KiCad netlist (as graph)
and the SPICE netlist. 
"""

import threading

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
