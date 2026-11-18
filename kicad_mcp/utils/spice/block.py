"""
Component and block classification for extracting simulatable sub-circuits.
"""
import re
from collections import deque

# lib_id for electrically transparent parts the traversal may pass straight through
_PERMEABLE_RE = re.compile(r"testpoint|mountinghole", re.I)

# default limits for growing a block (select_block)
DEFAULT_MAX_HOPS = 6
DEFAULT_MAX_SIZE = 60
DEFAULT_MAX_FANOUT = 10


def is_permeable(node: dict) -> bool:
    """Electrically transparent part (test point, mounting hole), the block
    traversal passes through it.

    Args:
        node: a component entry from CircuitGraph.nodes (type == 'component').
    """
    return bool(_PERMEABLE_RE.search(node.get("lib_id") or "")
                or _PERMEABLE_RE.search(node.get("name") or ""))


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
      - global:   power / ground nets (reported separately for the reference /
                  supply confirmation step, not treated as ports).
    Purely internal nets need no handling and are skipped.

    Args:
        graph: a built CircuitGraph instance.
        block_components: the component refs forming the block (from select_block).

    Returns:
        dict with ports, dangling and global_nets_touched.
    """
    block = {r.upper() for r in block_components}

    ports = []
    dangling = []
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
                "pins_outside": [_pin_record(c) for c in outside],
            })
        elif len(inside) == 1:
            dangling.append({"net": net_name, "pin": _pin_record(inside[0])})

    return {
        "ports": sorted(ports, key=lambda p: p["net"]),
        "dangling": sorted(dangling, key=lambda d: d["net"]),
        "global_nets_touched": sorted(global_nets),
    }


def select_block(graph, seed_refs, simulatable, max_hops=DEFAULT_MAX_HOPS,
                 max_size=DEFAULT_MAX_SIZE, max_fanout=DEFAULT_MAX_FANOUT):
    """Grow a simulatable sub-circuit outward from one or more seed components.

    BFS over the bipartite component/net graph. It expands through simulatable and
    permeable components and the signal nets between them, and stops at:
      - global nets (power / ground, i.e. graph.power_symbols),
      - components that are neither simulatable nor permeable (ICs without model, ...),
      - nets with a fan-out above max_fanout (likely a bus / shared rail).

    Args:
        graph: a built CircuitGraph instance.
        seed_refs: list of component references to start from.
        simulatable: refs with a complete SPICE element (SpiceNetlistParser.simulatable_refs).
        max_hops: max BFS hops (in components) from any seed before truncating.
        max_size: max number of components in the block before truncating.
        max_fanout: a net with more than this many connections is a stop.

    Returns:
        dict with success, block_components, ports, dangling, global_nets_touched,
        high_fanout (nets not followed: [{net, fanout}]) and the truncated flag/reason.
    """

    seeds = [r.upper() for r in seed_refs]

    unknown = [r for r in seeds if graph.nodes.get(r, {}).get("type") != "component"]
    if unknown:
        return {"success": False,
                "error": f"Not found in the schematic: {', '.join(unknown)} - "
                         "check the reference (e.g. R1, C3)."}

    no_model = [r for r in seeds if r not in simulatable and not is_permeable(graph.nodes[r])]
    if no_model:
        return {"success": False,
                "error": f"No simulation model: {', '.join(no_model)} - assign one in KiCad under "
                         "Symbol Properties -> Simulation Model."}

    block = set(seeds)
    high_fanout = {}
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

        for net in sorted(graph.adjacency_list[comp]):
            if net in graph.power_symbols:
                continue

            fanout = len(graph.adjacency_list[net])
            if fanout > max_fanout:
                high_fanout[net] = fanout
                continue

            for nb in sorted(graph.adjacency_list[net]):
                if nb in visited:
                    continue

                if nb not in simulatable and not is_permeable(graph.nodes[nb]):
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
        "block_components": sorted(block),
        "ports": boundary["ports"],
        "dangling": boundary["dangling"],
        "global_nets_touched": boundary["global_nets_touched"],
        "high_fanout": [{"net": n, "fanout": f} for n, f in sorted(high_fanout.items())],
        "truncated": truncated,
        "truncation_reason": truncation_reason,
    }


def suggest_port_role(port: dict) -> dict:
    """Suggest the UI role of one block port from its outside pin types.

    Any driver outside (output / power_out) -> 'input' (a source replaces it), only sinks
    outside (input / power_in) -> 'output' (left open). Anything else (passive,
    bidirectional, ...) is ambiguous -> 'output' with clarify=True, the user must check.

    Returns:
        dict with role ('input' | 'output') and clarify (bool).
    """
    outside_types = {
        (p.get("electrical_type") or "unspecified").split("+")[0]
        for p in port.get("pins_outside", [])
    }

    if outside_types & {"output", "power_out"}:     
        return {"role": "input", "clarify": False}
    if outside_types <= {"input", "power_in"}:      
        return {"role": "output", "clarify": False}
    return {"role": "output", "clarify": True}


def ground_nets(rails):
    """The touched rails that look like a ground net: 'GND...' or SPICE node '0'."""
    
    grounds = [n for n in rails if n == "0" or "GND" in n.upper()]
    return sorted(grounds, key=lambda n: n.upper() not in ("0", "GND"))


def block_warnings(block):
    """Pre-checks on a grown block
    
    Returns:
        list of messages: block truncated, nets not followed (high fan-out), open pins,
        complaints of the SPICE export, more than one ground net.
    """
    warnings = []
    if block.get("truncated"):
        warnings.append(
            f"Block was truncated ({block['truncation_reason']}) - "
            "the nets at the cut appear as ports."
        )
    for n in block.get("high_fanout", []):
        warnings.append(
            f"Net {n['net']} ({n['fanout']} connections) not followed - "
            "probably a bus or shared net."
        )
    for d in block.get("dangling", []):
        warnings.append(
            f"Open pin: {d['pin']['component']} pin {d['pin']['pin']} on net {d['net']}."
        )
    if block.get("export_warning"):
        warnings.append(f"KiCad reported during the SPICE export: {block['export_warning']}")
    rails = block["global_nets_touched"]
    grounds = ground_nets(rails)
    if len(grounds) > 1:
        warnings.append(
            f"Several ground nets ({', '.join(grounds)}), check the reference net. For the "
            "others enter 0 = connected to ground, leave empty = separate."
        )
    return warnings


def guess_voltage(net_name: str):
    """Guess a supply voltage from a power-net name: '+5V', '+3.3V', '3V3', '-12V'.
    """
    m = re.match(r"^([+-]?)(\d+(?:\.\d+)?)[Vv](\d*)", net_name)
    if not m:
        return None
    sign = -1.0 if m.group(1) == "-" else 1.0
    whole, frac = m.group(2), m.group(3)
    value = float(whole) + (float(frac) / (10 ** len(frac)) if frac else 0.0)
    return sign * value
