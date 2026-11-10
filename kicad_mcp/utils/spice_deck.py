"""
Builds an isolated SPICE deck for a block: exports the schematic's SPICE netlist via
kicad-cli, filters it to the block, assembles the runnable deck and validates it.
"""

import re
import sys
from collections import defaultdict

from kicad_mcp.utils.cli_drc import export_netlist
from kicad_mcp.utils.file_utils import hash_schematic
from kicad_mcp.utils.schematic_cache import CACHE_LOCK, get_entry


class SpiceNetlistParser:
    """
    Exports a schematic's SPICE netlist via kicad-cli and filters it to the lines of a single block (isolated Spicelist).
    """

    def __init__(self, schematic_path: str):
        self.schematic_path = schematic_path
        self.spice = None
        self.includes = []
        self.models = {}
        self.elements = []
        self.export_error = None    

    def export_spice(self, schematic_hash: str = None):
        """Get the SPICE netlist of the schematic, exported via kicad-cli only if the
        cached one was made from an older schematic state.

        Args:
            schematic_hash: hash_schematic() of the schematic if the caller already has it.
        """
        self.export_error = None
        if schematic_hash is None:
            try:
                schematic_hash = hash_schematic(self.schematic_path)
            except OSError as e:
                self.export_error = f"Schaltplan nicht lesbar: {e}"
                return

        with CACHE_LOCK:
            entry = get_entry(self.schematic_path)
            spice_is_current = (entry["spice"] is not None
                                and entry["spice_schematic_hash"] == schematic_hash)
            if spice_is_current:
                self.spice = entry["spice"]
                return

            spice, error = export_netlist(self.schematic_path, "spice")
            if error:
                self.export_error = error
                print(error, file=sys.stderr)
                return

            entry["spice"] = spice
            entry["spice_schematic_hash"] = schematic_hash
            self.spice = spice

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
        return e["name"][:1].upper() in _VALUE_DEVICES or model in self.models or bool(self.includes)

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
            dict with elements and models.
        """
        wanted = {r.upper() for r in block_components}

        kept_elements = [e for e in self.elements
                         if element_ref(e["name"], wanted) and self._is_simulatable(e)]

        used_models = {
            tok for e in kept_elements for tok in e["tokens"] if tok in self.models
        }
        kept_models = [self.models[n] for n in sorted(used_models)]

        return {
            "elements": [e["raw"] for e in kept_elements],
            "models": kept_models,
        }


_VALUE_DEVICES = set("RCLVIB")


def element_ref(name, refs):
    """Reference of an element line, KiCad prefixes the device letter if the
    reference does not start with it ('MQ2', 'XU1')."""
    if name.upper() in refs:
        return name.upper()
    if name[1:].upper() in refs:
        return name[1:].upper()
    return None


def node_count(tokens):
    """Number of nodes of an element line: two for R/C/L/V/I/B, otherwise all
    tokens before the model name."""

    if tokens[0][:1].upper() in _VALUE_DEVICES:
        return 2
    return len([t for t in tokens[1:] if "=" not in t]) - 1


def build_isolated_deck(kept_elements, reference_node, supply_nodes, ports, analysis,
                        models=None, includes=None, title=".title isolated block"):
    """Assemble a runnable SPICE deck for an isolated block.

    Maps the reference net to node 0, turns each global rail into an independent
    source against ground, each port into a source / load / nothing, and appends the analysis directive.

    Args:
        kept_elements: raw block element lines 
        reference_node: SPICE node tied to 0 (the reference net / node 0).
        supply_nodes: {node: source spec} without the reference node, each becomes an
            independent source to 0, e.g. {'+5V': 'DC 5 AC 1'}.
        ports: [(node, role, value)] from the user's per-port config,
            role 'input' | 'load' | 'output'.
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

    # input -> source 'Vin<i>', load -> passive 'R/C/Lload<i>' (R if no type given), output -> open
    for i, (node, role, value) in enumerate(ports or []):
        if role == "input":
            lines.append(f"Vin{i} {node} 0 {value}")
        elif role == "load":
            parts = (value or "").split(None, 1)
            dev = parts[0][:1].upper() if parts else "R"
            if dev in ("R", "C", "L") and len(parts) > 1:
                lines.append(f"{dev}load{i} {node} 0 {parts[1]}")
            else:
                lines.append(f"Rload{i} {node} 0 {value}")


    for raw in kept_elements:
        tokens = raw.split()
        n = node_count(tokens)
        tokens[1:1 + n] = ["0" if t == reference_node else t for t in tokens[1:1 + n]]
        if tokens[0][:1].upper() in ("R", "C", "L") and len(tokens) >= 4:
            # KiCad copies the whole Value field ('1n 50V C0G', '10k/1%'): keep the value
            # and real parameters (ic=0), drop the rest
            tokens = tokens[:3] + [tokens[3].split("/")[0]] + [t for t in tokens[4:] if "=" in t]
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

    value_re = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?[a-z]*$", re.I)

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
            and all(value_re.match(p) for p in params[1:4])):
        errors.append(".ac braucht 'dec|oct|lin <Punkte> <fStart> <fStop>', "
                      "z. B. '.ac dec 20 1 1Meg'.")
    elif analysis == ".tran" and not (
            len(params) >= 2 and all(value_re.match(p) for p in params[:2])):
        errors.append(".tran braucht '<Schritt> <Ende>', z. B. '.tran 1u 5m'.")

    for tokens in elements:
        if tokens[0][:1].upper() in ("R", "C", "L") and (
                len(tokens) < 4 or not value_re.match(tokens[3])):
            value = tokens[3] if len(tokens) > 3 else "leer"
            errors.append(f"{tokens[0]}: ungueltiger Wert '{value}' (z. B. DNP/NC?).")

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
        if e["name"][:1].upper() not in ("R", "C", "L"):
            continue
        pins = ref_pins.get(e["name"].upper())
        if not pins or sorted(pins) != ["1", "2"]:
            continue
        net_to_node.setdefault(pins["1"], e["tokens"][1])
        net_to_node.setdefault(pins["2"], e["tokens"][2])
    return net_to_node
