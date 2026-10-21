"""
Runs an assembled SPICE deck through ngspice (via PySpice) 
"""

import logging
import os
import sys
import tempfile
import threading
from pathlib import Path

from kicad_mcp.utils.cli_drc import find_kicad_cli
from kicad_mcp.utils.spice_deck import validate_deck

# So two overlapping runs cannot crash ngspice which would kill the server process.
_NGSPICE_LOCK = threading.Lock()


class _LogCollector(logging.Handler):
    """Collects PySpice/ngspice log records"""

    def __init__(self):
        super().__init__()
        self.records: list[str] = []

    def emit(self, record):
        self.records.append(f"{record.levelname}: {record.getMessage()}")


def _configure_ngspice_library() -> str | None:
    """Point PySpice at the ngspice shared library bundled with KiCad."""
    kicad_cli = find_kicad_cli()
    if not kicad_cli:
        return None

    bin_dir = os.path.dirname(kicad_cli)

    if sys.platform == "win32" and hasattr(os, "add_dll_directory") and os.path.isdir(bin_dir):
        try:
            os.add_dll_directory(bin_dir)
        except OSError:
            pass

    from PySpice.Spice.NgSpice.Shared import NgSpiceShared

    lib = "ngspice{}.dll" if sys.platform == "win32" else "libngspice{}.so"
    NgSpiceShared.LIBRARY_PATH = os.path.join(bin_dir, lib)
    return bin_dir


def run_deck(deck: str) -> dict:
    """Validate a complete SPICE deck and simulate in ngspice

    A deck that fails validate_deck is not handed to ngspice at all.

    Args:
        deck: a runnable SPICE deck.

    Returns:
        dict with:
          success (bool)      - operating point solved and voltages were read.
          validation_failed   - True if validate_deck rejected the deck (not run).
          voltages (dict)     - {node: volts}, empty on failure.
          errors (list[str])  - validation errors, fatal ngspice messages / exceptions.
          warnings (list[str])- validation warnings and non-fatal ngspice messages.
          log (str)           - full captured ngspice/PySpice log.
    """
    out = {"success": False, "validation_failed": False, "voltages": {},
           "errors": [], "warnings": [], "log": ""}

    check = validate_deck(deck)
    out["warnings"] += check["warnings"]
    if check["errors"]:
        out["errors"] = check["errors"]
        out["validation_failed"] = True
        return out

    try:
        bin_dir = _configure_ngspice_library()
    except ImportError:
        out["errors"].append(
            "PySpice ist nicht installiert. Installiere es im Server-Env "
        )
        return out

    if bin_dir is None:
        out["errors"].append(
            "kicad-cli/ngspice nicht gefunden. Ist KiCad 9.0+ installiert bzw. "
            "KICAD_APP_PATH korrekt gesetzt?"
        )
        return out

    from PySpice.Spice.Parser import SpiceParser

    with _NGSPICE_LOCK:
        collector = _LogCollector()
        pyspice_logger = logging.getLogger("PySpice")
        prev_level = pyspice_logger.level
        pyspice_logger.addHandler(collector)
        pyspice_logger.setLevel(logging.INFO)

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".cir", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(deck)
                tmp_path = Path(tmp.name)

            parser = SpiceParser(path=str(tmp_path))
            circuit = parser.build_circuit()
            if hasattr(circuit, "_includes"):
                circuit._includes.clear()

            simulator = circuit.simulator(simulator="ngspice-shared")

            #TODO: das kann ja gewählt werden
            analysis = simulator.operating_point()

            nodes = dict(analysis.nodes)
            for name, waveform in nodes.items():
                try:
                    out["voltages"][name] = float(waveform[0])
                except (TypeError, IndexError, ValueError):
                    pass

            out["success"] = bool(out["voltages"]) or not nodes

        except Exception as e:
            out["errors"].append(f"{type(e).__name__}: {e}")
        finally:
            pyspice_logger.removeHandler(collector)
            pyspice_logger.setLevel(prev_level)
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

   
    for line in dict.fromkeys(collector.records):
        low = line.lower()
        message = line.split(":", 1)[-1].strip().lower()
        if low.startswith("error") and not message.startswith("note:"):
            out["errors"].append(line)
        elif low.startswith("warning") and "spinit" not in low \
                and "python keyword" not in low and "unsupported ngspice" not in low:
            out["warnings"].append(line)
    out["log"] = "\n".join(collector.records)

    if out["errors"]:
        out["success"] = False
    return out


def format_result(result: dict) -> str:
    """Render a run_deck() result as a short human-readable report."""
    lines = []
    if result["validation_failed"]:
        lines.append("Validierung FEHLGESCHLAGEN - ngspice wurde nicht gestartet.")
    elif result["success"]:
        lines.append("Simulation OK (Arbeitspunkt gelöst).")
    else:
        lines.append("Simulation FEHLGESCHLAGEN.")

    if result["voltages"]:
        lines.append("")
        lines.append("Knotenspannungen:")
        for node, v in sorted(result["voltages"].items()):
            lines.append(f"  {node} = {v:.4g} V")

    if result["errors"]:
        lines.append("")
        lines.append("Fehler:")
        for e in result["errors"]:
            lines.append(f"  - {e}")

    if result["warnings"]:
        lines.append("")
        lines.append("Warnungen:")
        for w in result["warnings"]:
            lines.append(f"  - {w}")

    return "\n".join(lines)
