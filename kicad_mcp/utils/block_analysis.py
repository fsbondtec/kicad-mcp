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


def _pin_record(conn: dict) -> dict:
    """Flatten a netlist connection into a pin record."""
    return {
        "component": conn["component"],
        "pin": conn["pin"],
        "pinfunction": conn.get("pinfunction"),
        "electrical_type": conn.get("electrical_type"),
    }


def classify_block_boundary(graph, block_components):
    """Classify the nets around a selected block on the pin level.

    For every net that touches the block:
      - port:     non-global net with pins inside AND outside the block,
      - dangling: net with exactly one pin inside and none outside (a stub),
      - internal: all pins inside the block (a purely internal net),
      - global:   power / ground nets (reported separately for the reference /
                  supply confirmation step, not treated as ports).

    Args:
        graph: a built CircuitGraph instance.
        block_components: the component refs forming the block (from select_block).

    Returns:
        dict with ports, dangling, internal_nets and global_nets_touched.
    """
    block = {r.upper() for r in block_components}

    ports = []
    dangling = []
    internal_nets = []
    global_nets = []

    for net_name, conns in graph.netlist_data["nets"].items():
        inside = [c for c in conns if c["component"].upper() in block]
        if not inside:
            continue  

        if net_name in graph.power_symbols:
            global_nets.append(net_name)
            continue

        outside = [c for c in conns if c["component"].upper() not in block]

        if outside:
            ports.append({
                "net": net_name,
                "pins_inside": [_pin_record(c) for c in inside],
                "pins_outside": [_pin_record(c) for c in outside],
            })
        elif len(inside) == 1:
            dangling.append({"net": net_name, "pin": _pin_record(inside[0])})
        else:
            internal_nets.append(net_name)

    return {
        "ports": sorted(ports, key=lambda p: p["net"]),
        "dangling": sorted(dangling, key=lambda d: d["net"]),
        "internal_nets": sorted(internal_nets),
        "global_nets_touched": sorted(global_nets),
    }


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

    boundary = classify_block_boundary(graph, block)

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
        "ports": boundary["ports"],
        "dangling": boundary["dangling"],
        "internal_nets": boundary["internal_nets"],
        "global_nets_touched": boundary["global_nets_touched"],
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
