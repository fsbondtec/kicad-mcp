"""
Component and block classification for extracting simulatable sub-circuits.
"""
import re
from collections import deque

# Primitive devices reducible to a SPICE element, incl. common variants
# (C_Polarized, R_Small, D_Schottky, ...).
_SIMULATABLE_NAME_RE = re.compile(r"^(R|C|L|D)(_.*)?$")

# Sim.Device values that denote a SPICE primitive
_PRIMITIVE_SIM_DEVICES = {"R", "C", "L", "D"}

# lib_id / name fragments for electrically transparent parts the traversal may
# pass straight through: test points, mounting holes and net ties.
_PERMEABLE_RE = re.compile(r"testpoint|mountinghole|nettie", re.I)

def classify_component(node: dict) -> str:
    """Classify a component node as 'simulatable', 'permeable' or 'boundary'.

    - permeable:   electrically transparent, block traversal passes through them.
    - simulatable: a primitive passive or diode (R/C/L/D and variants)
    - boundary:    everything else (ICs, resistor arrays, varistors, ...).

    Args:
        node: a component entry from CircuitGraph.nodes (type == 'component').
    """
    lib_id = node.get("lib_id") or ""
    name = node.get("name") or ""
    sim_fields = node.get("sim_fields") or {}

    if _PERMEABLE_RE.search(lib_id) or _PERMEABLE_RE.search(name):
        return "permeable"

    if _SIMULATABLE_NAME_RE.match(name):
        return "simulatable"

    sim_device = (sim_fields.get("Sim.Device") or "").upper()
    if sim_device in _PRIMITIVE_SIM_DEVICES:
        return "simulatable"

    return "boundary"


def select_block(graph, seed_refs, max_hops=6, max_size=60, max_fanout=8):
    """Grow a simulatable sub-circuit outward from one or more seed components.

    BFS over the bipartite component/net graph. It expands through simulatable and
    permeable components and the signal nets between them, and stops at:
      - global nets (power / ground, i.e. graph.power_symbols),
      - boundary components (classify_component == 'boundary'),
      - nets with a fan-out above max_fanout (likely a bus / shared rail).

    Args:
        graph: a built CircuitGraph instance.
        seed_refs: component reference(s) to start from.
        max_hops: max BFS hops (in components) from any seed before truncating.
        max_size: max number of components in the block before truncating.
        max_fanout: a net with more than this many connections is a stop.

    Returns:
        dict with success, block_components, block_nets, boundary_components,
        stopped_nets, truncated flag and the applied limits.
    """

    if isinstance(seed_refs, str):
        seed_refs = [seed_refs]
    seeds = [r.upper() for r in seed_refs]

    missing = [r for r in seeds if r not in graph.adjacency_list
               or graph.nodes.get(r, {}).get("type") != "component"]
    if missing:
        return {"success": False, "error": "Please enter valid components",
                "missing": missing}

    block = set(seeds)                 
    block_nets = set()                
    boundary_components = {}          
    stopped_nets = {"global": {}, "high_fanout": {}}
    visited = set(seeds)
    truncated = False
    truncation_reason = None

    queue = deque((s, 0) for s in seeds)

    while queue:
        comp, hop = queue.popleft()

        if hop >= max_hops:
            truncated = True
            truncation_reason = f"max_hops={max_hops} reached"
            continue

        for net in graph.adjacency_list[comp]:
            if net in graph.power_symbols:
                stopped_nets["global"].setdefault(net, [])
                continue

            fanout = len(graph.adjacency_list[net])
            if fanout > max_fanout:
                stopped_nets["high_fanout"][net] = fanout
                continue

            block_nets.add(net)

            for nb in graph.adjacency_list[net]:
                if nb in visited:
                    continue

                cls = classify_component(graph.nodes[nb])
                if cls == "boundary":
                    boundary_components.setdefault(nb, net)
                    continue

                if len(block) >= max_size:
                    truncated = True
                    truncation_reason = f"max_size={max_size} reached"
                    continue

                visited.add(nb)
                block.add(nb)
                queue.append((nb, hop + 1))

    return {
        "success": True,
        "seeds": seeds,
        "block_components": sorted(block),
        "block_size": len(block),
        "block_nets": sorted(block_nets),
        "boundary_components": [
            {"component": ref, "via_net": net}
            for ref, net in sorted(boundary_components.items())
        ],
        "stopped_nets": {
            "global": sorted(stopped_nets["global"]),
            "high_fanout": [
                {"net": n, "fanout": f}
                for n, f in sorted(stopped_nets["high_fanout"].items())
            ],
        },
        "truncated": truncated,
        "truncation_reason": truncation_reason,
        "limits": {"max_hops": max_hops, "max_size": max_size,
                   "max_fanout": max_fanout},
    }
