"""
Builds an isolated SPICE deck for a block: exports the schematic's SPICE netlist via
kicad-cli, filters it to the block, assembles the runnable deck and validates it.
"""

import os
import re
import sys
import subprocess
import tempfile
import threading
from collections import defaultdict

from kicad_mcp.utils.cli_drc import find_kicad_cli
from kicad_mcp.utils.file_utils import hash_file


# Cache of kicad-cli SPICE exports
_SPICE_EXPORT_CACHE: dict = {}

# wait for the running export and then hit the cache
_SPICE_EXPORT_LOCK = threading.Lock()


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

    def export_spice(self):
        """Export the SPICE netlist via kicad-cli.

        A successful export is cached per schematic (keyed by file hash) so repeated runs reuse it 
        """
        self.export_error = None
        with _SPICE_EXPORT_LOCK:
            self._export_spice_locked()

    def _export_spice_locked(self):
        try:
            current_hash = hash_file(self.schematic_path)
        except OSError as e:
            self.export_error = f"Schaltplan nicht lesbar: {e}"
            return

        cached = _SPICE_EXPORT_CACHE.get(self.schematic_path)
        if cached and cached["hash"] == current_hash:
            self.spice = cached["spice"]
            return

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                output_file = os.path.join(temp_dir, "netlist.cir")

                kicad_cli = find_kicad_cli()
                if not kicad_cli:
                    self.export_error = (
                        "kicad-cli nicht gefunden. KiCad 9.0+ installiert bzw. "
                        "KICAD_APP_PATH korrekt gesetzt?"
                    )
                    print(self.export_error, file=sys.stderr)
                    return

                cmd = [
                    kicad_cli,
                    "sch",
                    "export",
                    "netlist",
                    "--format",
                    "spice",
                    "--output",
                    output_file,
                    self.schematic_path,
                ]

                process = subprocess.run(
                    cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL
                )

                if process.returncode != 0:
                    self.export_error = (
                        f"kicad-cli SPICE-Export fehlgeschlagen (Code {process.returncode}): "
                        f"{process.stderr.strip() or 'keine Fehlerausgabe'}"
                    )
                    print(f"SPICE export failed: {self.export_error}", file=sys.stderr)
                    return

                if os.path.exists(output_file):
                    with open(output_file, "r", encoding="latin-1") as f:
                        self.spice = f.read()
                    _SPICE_EXPORT_CACHE[self.schematic_path] = {
                        "hash": current_hash,
                        "spice": self.spice,
                    }
                else:
                    self.export_error = (
                        "kicad-cli meldete Erfolg, aber die Netlist-Datei wurde nicht erzeugt."
                    )
                    print(self.export_error, file=sys.stderr)

        except Exception as e:
            self.export_error = f"Ausnahme beim SPICE-Export: {e}"
            print(self.export_error, file=sys.stderr)

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

    def filter_block(self, block_components):
        """
        Keeps only the element lines belonging to the block and the model cards they
        reference.

        Args:
            block_components: component references forming the block.

        Returns:
            dict with elements, models, includes and missing_refs.
        """
        wanted = {r.upper() for r in block_components}

        def ref_of(name):
            if name.upper() in wanted:
                return name.upper()
            if name[:1].upper() == "X" and name[1:].upper() in wanted:
                return name[1:].upper()
            return None

        kept_elements = [e for e in self.elements if ref_of(e["name"])]
        found_refs = {ref_of(e["name"]) for e in kept_elements}
        missing = sorted(wanted - found_refs)

        used_models = {
            tok for e in kept_elements for tok in e["tokens"] if tok in self.models
        }
        kept_models = [self.models[n] for n in sorted(used_models)]

        has_subckt_instance = any(e["name"][:1].upper() == "X" for e in kept_elements)
        kept_includes = list(self.includes) if has_subckt_instance else []

        return {
            "elements": [e["raw"] for e in kept_elements],
            "models": kept_models,
            "includes": kept_includes,
            "missing_refs": missing,
        }


# device letters whose element has exactly two nodes in one Spice Line 
_TWO_NODE = set("RCLDVI")


def build_isolated_deck(kept_elements, reference_node, supply_nodes, ports, analysis,
                        models=None, includes=None, title=".title isolated block"):
    """Assemble a runnable SPICE deck for an isolated block.

    Maps the reference net to node 0, turns each global rail into an independent DC
    source against ground, each port into a source / load / nothing, and appends the analysis directive.

    Args:
        kept_elements: raw block element lines 
        reference_node: SPICE node tied to 0 (the reference net / node 0).
        supply_nodes: {node: voltage} each becomes an independent DC source to 0.
        ports: [(node, role, value)] from the user's per-port config,
            role 'input' | 'load' | 'output'.
        analysis: analysis directive, e.g. '.op' or '.ac dec 20 1 1Meg'.
        models: model/subckt card lines referenced by the block (from filter_block).
        includes: .include lines needed by the block (from filter_block).
        title: deck title line.

    Returns:
        the deck text as a string.
    """
    lines = [title]

    lines.extend(includes or [])
    lines.extend(models or [])

    for i, (node, voltage) in enumerate(sorted(supply_nodes.items()), start=1):
        if node == reference_node:
            continue
        lines.append(f"V{i}_supply {node} 0 DC {voltage}")

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

    # block elements: reference node -> 0 on two-node devices, KiCad value annotations
    # stripped from passives ('4.7u/50V/X7R' -> '4.7u'); other devices are kept as-is
    for raw in kept_elements:
        tokens = raw.split()
        letter = tokens[0][:1].upper()
        if letter in _TWO_NODE:
            tokens[1:3] = ["0" if t == reference_node else t for t in tokens[1:3]]
            if letter in ("R", "C", "L") and len(tokens) >= 4:
                tokens[3] = tokens[3].split("/")[0].strip()
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
    analysis = next((l.split()[0].lower() for l in lines
                     if l.lower().startswith((".op", ".ac", ".tran", ".dc"))), ".op")

    if not sources:
        errors.append("Keine Quelle im Deck - mindestens einen Port als input festlegen.")

    # SPICE number with optional exponent and unit suffix: 309k, 1Meg, 4.7u, 1e-9
    value_re = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?[a-z]*$", re.I)
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
        if letter in _TWO_NODE:
            nodes = tokens[1:3]
        elif letter == "X":    
            nodes = [t for t in tokens[1:] if "=" not in t][:-1]
        else:
            nodes = []
        roots = [find(n) for n in nodes]
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
        errors.append(".ac braucht eine AC-Quelle - einen input-Port z. B. auf 'AC 1' setzen.")
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
