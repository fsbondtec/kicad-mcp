"""
Component and block classification for extracting simulatable sub-circuits.
"""
import re
from collections import deque

# lib_id / name fragments for electrically transparent parts the traversal may
# pass straight through: test points and mounting holes.
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
                "pins_inside": [_pin_record(c) for c in inside],
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
        seed_refs: component reference(s) to start from.
        simulatable: refs with a complete SPICE element (SpiceNetlistParser.simulatable_refs).
        max_hops: max BFS hops (in components) from any seed before truncating.
        max_size: max number of components in the block before truncating.
        max_fanout: a net with more than this many connections is a stop.

    Returns:
        dict with success, block_components, ports, dangling, global_nets_touched,
        high_fanout (nets not followed: [{net, fanout}]) and the truncated flag/reason.
    """

    if isinstance(seed_refs, str):
        seed_refs = [seed_refs]
    seeds = [r.upper() for r in seed_refs]

    missing = [r for r in seeds if r not in graph.adjacency_list
               or graph.nodes.get(r, {}).get("type") != "component"]
    if missing:
        return {"success": False,
                "error": f"Unbekannte Bauteile: {', '.join(missing)}"}

    no_model = [r for r in seeds if r not in simulatable and not is_permeable(graph.nodes[r])]
    if no_model:
        return {"success": False,
                "error": f"Kein Simulationsmodell: {', '.join(no_model)} - in KiCad unter "
                         "Symboleigenschaften -> Simulationsmodell zuweisen."}

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

        for net in graph.adjacency_list[comp]:
            if net in graph.power_symbols:
                continue

            fanout = len(graph.adjacency_list[net])
            if fanout > max_fanout:
                high_fanout[net] = fanout
                continue

            for nb in graph.adjacency_list[net]:
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


def reference_net(rails):
    """Return the ground net among the touched rails, or None if there is none."""
    return next((n for n in rails if "GND" in n.upper()), None)


def block_warnings(block):
    """Pre-checks on a grown block
    
    Returns:
        list of messages: block truncated, nets not followed (high fan-out), open pins,
        rails without a recognisable voltage.
    """
    warnings = []
    if block.get("truncated"):
        warnings.append(
            f"Block wurde abgeschnitten ({block['truncation_reason']}) - "
            "die Schnittstellen erscheinen als Ports."
        )
    for n in block.get("high_fanout", []):
        warnings.append(
            f"Netz {n['net']} ({n['fanout']} Anschluesse) nicht weiterverfolgt - "
            "vermutlich Bus oder Sammelnetz."
        )
    for d in block.get("dangling", []):
        warnings.append(
            f"Offener Pin: {d['pin']['component']} Pin {d['pin']['pin']} an Netz {d['net']}."
        )
    rails = block["global_nets_touched"]
    reference = reference_net(rails)
    unknown = [r for r in rails if r != reference and guess_voltage(r) is None]
    if unknown:
        warnings.append(
            f"Keine Spannung erkennbar fuer {', '.join(unknown)} - "
            "ohne Eintrag in der UI bekommen diese Netze keine Quelle."
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
