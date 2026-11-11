"""
Builds an isolated SPICE deck for a block: grows the block from the seeds, filters the
schematic's SPICE netlist to the block, assembles the runnable deck and validates it.
"""

import re
from collections import defaultdict

from kicad_mcp.utils.file_utils import hash_schematic
from kicad_mcp.utils.schematic_cache import get_graph_data, get_spice_netlist
from kicad_mcp.utils.spice.block import (
    block_warnings, ground_nets, select_block, suggest_port_role,
)

# a SPICE number: digits, optional exponent, then letters for the suffix and unit ("4.7k", "1e-6", "100nF", "1Meg")
SPICE_VALUE_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?[a-z]*$", re.I)

# passive parts
PASSIVE_DEVICES = frozenset("RCL")

# the letter is  decimal point: '4k7' = 4.7k
_RKM_RE = re.compile(r"^(\d*)([RrkKMGmunp])(\d+)$")

# RKM letters that are no SPICE prefix as written, all others stay as they are
_RKM_PREFIX = {"R": "", "r": "", "K": "k", "M": "Meg"}

# part values use 'M' for mega like KiCad, SPICE reads 'M' as milli: '1M' -> '1Meg'
MEGA_M_RE = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+))M(?![eE][gG])")

# parts with exactly two nodes and a value or source spec instead of a model name
TWO_NODE_DEVICES = PASSIVE_DEVICES | frozenset("VIB")


class SpiceNetlistParser:
    """
    Parses a schematic's SPICE netlist (kicad-cli export) and filters it to the lines of a single block (isolated Spicelist).
    """

    def __init__(self, spice: str):
        self.spice = spice
        self.includes = []
        self.models = {}
        self.elements = []

    def parse(self):
        """
        Splits the raw deck into includes, model cards and element lines.
        """
        if not self.spice:
            return

        for raw in self.spice.splitlines():
            line = raw.strip()
            if not line or line.startswith("*"):
                continue

            low = line.lower()
            if low.startswith(".include"):
                self.includes.append(line)
            elif low.startswith(".model") or low.startswith(".subckt"):
                parts = line.split()
                if len(parts) >= 2:
                    self.models[parts[1]] = line
            elif line.startswith("."):
                continue  
            else:
                tokens = line.split()
                self.elements.append({"name": tokens[0], "tokens": tokens, "raw": line})

    def _is_simulatable(self, e):
        """Complete element: nodes plus a value or a model that is defined in the deck"""
        n = node_count(e["tokens"])
        if n < 1 or len(e["tokens"]) < n + 2:
            return False
        model = [t for t in e["tokens"][1:] if "=" not in t][-1]
        return e["name"][:1].upper() in TWO_NODE_DEVICES or model in self.models or bool(self.includes)

    def simulatable_refs(self, known_refs):
        """Refs KiCad exported as a complete element

        Args:
            known_refs: all component references of the schematic.

        Returns:
            set of upper-case references.
        """
        refs = {r.upper() for r in known_refs}
        return {element_ref(e["name"], refs) for e in self.elements
                if self._is_simulatable(e)} - {None}

    def filter_block(self, block_components):
        """
        Keeps only the element lines belonging to the block and the model cards they
        reference. 

        Args:
            block_components: component references forming the block.

        Returns:
            dict with elements (the parsed element dicts: name, tokens, raw) and models.
        """
        wanted = {r.upper() for r in block_components}

        kept_elements = [e for e in self.elements
                         if element_ref(e["name"], wanted) and self._is_simulatable(e)]

        used_models = {
            tok for e in kept_elements for tok in e["tokens"] if tok in self.models
        }
        kept_models = [self.models[n] for n in sorted(used_models)]

        return {
            "elements": kept_elements,
            "models": kept_models,
        }

def element_ref(name, refs):
    """Reference of an element line, KiCad prefixes the device letter if the
    reference does not start with it ('MQ2', 'XU1')."""
    if name.upper() in refs:
        return name.upper()
    if name[1:].upper() in refs:
        return name[1:].upper()
    return None


def part_value(value):
    """SPICE number of a passive's Value field when KiCad exported it unconverted
    because of an extra ('5k6;1W', '2200uF;63V', '10k/1%'): cut at ';' or '/', resolve
    RKM ('5k6' -> '5.6k'), 'M' as mega ('1M' -> '1Meg') and 'µ' ('4.7µF' -> '4.7uF')."""
    
    value = re.split(r"[;/]", value)[0].replace("µ", "u").replace("μ", "u")
    rkm = _RKM_RE.match(value)
    if rkm:
        whole, letter, frac = rkm.groups()
        return f"{whole or 0}.{frac}{_RKM_PREFIX.get(letter, letter)}"
    return MEGA_M_RE.sub(r"\1Meg", value)


def node_count(tokens):
    """Number of nodes of an element line: two for R/C/L/V/I/B, otherwise all
    tokens before the model name."""

    if tokens[0][:1].upper() in TWO_NODE_DEVICES:
        return 2
    return len([t for t in tokens[1:] if "=" not in t]) - 1


def build_isolated_deck(kept_elements, reference_node, supply_nodes, ports, analysis,
                        models=None, includes=None, title=".title isolated block"):
    """Assemble a runnable SPICE deck for an isolated block.

    Maps the reference net to node 0, turns each global rail into an independent
    source against ground, each port into a source / load / nothing, and appends the analysis directive.

    Args:
        kept_elements: block element dicts from filter_block (name, tokens, raw).
        reference_node: SPICE node tied to 0 (the reference net / node 0).
        supply_nodes: {node: source spec} without the reference node, each becomes an
            independent source to 0, e.g. {'+5V': 'DC 5 AC 1'}.
        ports: [(node, role, value, load_type)] from the user's per-port config,
            role 'input' | 'load' | 'output'; value is the source spec for input and
            the part value for load, load_type 'R' | 'C' | 'L' (only used for load).
        analysis: analysis directive, e.g. '.op' or '.ac dec 20 1 1Meg'.
        models: model/subckt card lines referenced by the block (from filter_block).
        includes: .include lines of the export.
        title: deck title line.

    Returns:
        the deck text as a string.
    """
    lines = [title, ".options savecurrents"]   

    lines.extend(includes or [])
    lines.extend(models or [])

    for i, (node, spec) in enumerate(sorted(supply_nodes.items()), start=1):
        lines.append(f"V{i}_supply {node} 0 {spec}")

    # input -> source 'Vin<i>', load -> passive 'R/C/Lload<i>', output -> open
    for i, (node, role, value, load_type) in enumerate(ports or []):
        if role == "input":
            lines.append(f"Vin{i} {node} 0 {value}")
        elif role == "load":
            lines.append(f"{load_type}load{i} {node} 0 {value}")


    for element in kept_elements:
        tokens = list(element["tokens"])
        n = node_count(tokens)
        tokens[1:1 + n] = ["0" if t == reference_node else t for t in tokens[1:1 + n]]
        if tokens[0][:1].upper() in PASSIVE_DEVICES and len(tokens) >= 4:
            # KiCad copies the whole Value field ('1n 50V C0G', '10k/1%'): keep the value
            # and real parameters (ic=0), drop the rest
            tokens = tokens[:3] + [part_value(tokens[3])] + [t for t in tokens[4:] if "=" in t]
        lines.append(" ".join(tokens))

    lines.append(analysis)
    lines.append(".end")
    return "\n".join(lines)


def validate_deck(deck: str) -> dict:
    """Static checks on an assembled deck before it is handed to ngspice.

    Args:
        deck: the deck text from build_isolated_deck.

    Returns:
        dict with errors (deck cannot run meaningfully) and warnings.
    """
    errors, warnings = [], []
    lines = deck.splitlines()
    elements = [l.split() for l in lines if l[:1].isalpha()]    
    sources = [t for t in elements if t[0][:1].upper() in ("V", "I")]

    if not sources:
        errors.append("Keine Quelle im Deck - mindestens einen Port als input festlegen.")

    directives = [l.split() for l in lines if l.startswith(".") and l.split()[0].lower()
                  not in (".title", ".options", ".include", ".lib", ".model", ".subckt", ".ends", ".end")]
    
    analysis = directives[0][0].lower() if directives else None
    params = directives[0][1:] if directives else []

    if analysis is None:
        errors.append("Keine Analyse im Deck - .op, .ac oder .tran angeben.")
    elif analysis not in (".op", ".ac", ".tran"):
        errors.append(f"Analyse '{analysis}' nicht unterstuetzt, .op, .ac oder .tran verwenden.")
    elif analysis == ".ac" and not (
            len(params) >= 4 and params[0].lower() in ("dec", "oct", "lin")
            and all(SPICE_VALUE_RE.match(p) for p in params[1:4])):
        errors.append(".ac braucht 'dec|oct|lin <Punkte> <fStart> <fStop>', "
                      "z. B. '.ac dec 20 1 1Meg'.")
    elif analysis == ".tran" and not (
            len(params) >= 2 and all(SPICE_VALUE_RE.match(p) for p in params[:2])):
        errors.append(".tran braucht '<Schritt> <Ende>', z. B. '.tran 1u 5m'.")

    for tokens in elements:
        if tokens[0][:1].upper() in PASSIVE_DEVICES and (
                len(tokens) < 4 or not SPICE_VALUE_RE.match(tokens[3])):
            if len(tokens) < 4 or not tokens[3]:
                errors.append(f"{tokens[0]}: kein Wert (Bauteil DNP/NC?).")
            else:
                errors.append(f"{tokens[0]}: Wert '{tokens[3]}' ist keine SPICE-Zahl.")

    seen_pairs = {}
    for name, a, b, *_ in sources:
        pair = frozenset((a, b))
        if name[:1].upper() != "V":
            continue
        if len(pair) < 2:
            errors.append(f"{name}: beide Anschluesse am selben Knoten {a}.")
        elif pair in seen_pairs:
            errors.append(f"{name} und {seen_pairs[pair]} liegen parallel ({a}/{b}) - "
                          "einen der beiden Ports nicht als input festlegen.")
        else:
            seen_pairs[pair] = name

    # union-find over every element that conducts DC
    parent = {"0": "0"}

    def find(n):
        parent.setdefault(n, n)
        while parent[n] != n:
            n = parent[n]
        return n

    for tokens in elements:
        letter = tokens[0][:1].upper()
        roots = [find(n) for n in tokens[1:1 + node_count(tokens)]]
        if letter in ("C", "I"):
            continue
        for r in roots[1:]:
            parent[r] = roots[0]

    floating = sorted(n for n in parent if find(n) != find("0"))
    if floating:
        errors.append(
            f"Kein DC-Pfad nach Masse: {', '.join(floating)} - Port als load "
            "(z. B. R 1G) festlegen oder Block erweitern."
        )

    source_lines = [" ".join(t) for t in sources]
    if analysis == ".ac" and not any(re.search(r"\bAC\b", l, re.I) for l in source_lines):
        errors.append(".ac braucht eine AC-Quelle - bei einem input-Port oder einer "
                      "Versorgung eine AC-Amplitude eintragen (z. B. 1).")
    if analysis == ".tran" and not any(
            re.search(r"\b(SIN|PULSE|PWL|EXP)\s*\(", l, re.I) for l in source_lines):
        warnings.append(".tran nur mit DC-Quellen - Ergebnis ist ein konstanter Verlauf.")

    return {"errors": errors, "warnings": warnings}


def build_net_node_map(netlist_nets, spice_elements):
    """Map each KiCad net name to the node name KiCad writes in the SPICE deck.

    Args:
        netlist_nets: parsed {net_name: [{"component", "pin", ...}]} dict.
        spice_elements: parsed SPICE elements [{"name", "tokens", ...}].

    Returns:
        {net_name: spice_node} for every net reachable through a passive.
    """
    # reference -> {pin: net}
    ref_pins = defaultdict(dict)
    for net, conns in netlist_nets.items():
        for c in conns:
            ref_pins[c["component"].upper()][c["pin"]] = net

    net_to_node = {}
    for e in spice_elements:
        if e["name"][:1].upper() not in PASSIVE_DEVICES:
            continue
        pins = ref_pins.get(e["name"].upper())
        if not pins or sorted(pins) != ["1", "2"]:
            continue
        net_to_node.setdefault(pins["1"], e["tokens"][1])
        net_to_node.setdefault(pins["2"], e["tokens"][2])
    return net_to_node


def grow_block(project_path, schematic_path, seed_components):
    """Export the SPICE netlist and grow the block from the seeds over the parts KiCad
    exported with a value or simulation model.

    Returns: graph, sp, block
    """

    seeds = [s.strip() for s in (seed_components or "").split(",") if s.strip()]

    try:
        schematic_hash = hash_schematic(schematic_path)
    except OSError as e:
        return None, None, {"success": False, "error": f"Schaltplan nicht lesbar: {e}"}

    try:
        graph, _ = get_graph_data(project_path, schematic_path, schematic_hash)
    except RuntimeError as e:
        return None, None, {"success": False, "error": str(e)}
    spice, export_error = get_spice_netlist(schematic_path, schematic_hash)
    if not spice:
        return graph, None, {"success": False,
                             "error": export_error or "SPICE-Export fehlgeschlagen"}
    sp = SpiceNetlistParser(spice)
    sp.parse()
    components = [r for r, n in graph.nodes.items() if n.get("type") == "component"]
    return graph, sp, select_block(graph, seeds, sp.simulatable_refs(components))


def select_ports(project_path, schematic_path, seed_components):
    """Grow the block from the seeds and pre-fill its ports for the UI.

    Returns (graph, block, ports): ports carry the suggested role, clarify
    flag and readable outside pins.
    """

    graph, _, block = grow_block(project_path, schematic_path, seed_components)
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


def assemble_deck(project_path: str, schematic_path: str, seed_components: str,
                   ports: list, analysis: str = ".op", reference_net: str = "",
                   supplies: list = None):
    """Rebuild the block and assemble the isolated SPICE deck from the ports and supplies.

    Returns: deck is the SPICE text, or None with an error
    message; warnings are the block pre-checks.
    """

    # the ports come from the UI, only the block itself is rebuilt
    graph, sp, block = grow_block(project_path, schematic_path, seed_components)
    if not block.get("success"):
        return None, f"Fehler: {block['error']}", []

    rails = block["global_nets_touched"]
    grounds = ground_nets(rails)
    reference_net = reference_net or (grounds[0] if grounds else None)

    filtered = sp.filter_block(block["block_components"])
    if not filtered["elements"]:
        return None, (
            "Fehler: keine simulierbaren Bauteile im Block gefunden. "
            "Seeds muessen Bauteile mit Wert oder Simulationsmodell sein."
        ), []

    # KiCad renames nets in the SPICE export ('Net-(D1-A)' -> 'Net-_D1-A_')
    net_map = build_net_node_map(graph.netlist_data["nets"], sp.elements)
    node = lambda net: net_map.get(net, net)

    block_nodes = set()
    for element in filtered["elements"]:
        tokens = element["tokens"]
        block_nodes.update(tokens[1:1 + node_count(tokens)])

    # without node 0 the deck has no reference and every node floats
    if reference_net is None and "0" not in block_nodes:
        remedy = ("bitte in der UI ein Bezugsnetz waehlen." if rails else
                  "in KiCad ein Masse-Symbol (z. B. GND) an das Bezugsnetz des Blocks setzen.")
        return None, f"Fehler: kein Massenetz (Knoten 0) am Block - {remedy}", []
    if reference_net is not None and node(reference_net) not in block_nodes:
        return None, (
            f"Fehler: Bezugsnetz {reference_net} ist mit keinem Bauteil des Blocks verbunden "
            "- ein Netz waehlen, an dem der Block haengt."
        ), []

    supply_nodes = {s["net"]: s["value"] for s in supplies or []
                    if (s.get("value") or "").strip() and s["net"] != reference_net}

    warnings = block_warnings(block)

    unpowered = [r for r in rails
                 if r != reference_net and r not in grounds and r not in supply_nodes]
    if unpowered:
        warnings.append(
            f"Keine Quelle an {', '.join(unpowered)} - diese Netze liegen nicht auf ihrer "
            "Spannung, sondern haengen nur an den Bauteilen des Blocks."
        )

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
        ports=[(node(p.get("net")), p.get("role"), p.get("value"), p.get("load_type"))
               for p in ports or []],
        analysis=analysis or ".op",
        models=filtered["models"],
        includes=sp.includes,
        title=f".title isolated block ({'+'.join(block['block_components'])})",
    )
    return deck, None, warnings
