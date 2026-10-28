"""
Runs an assembled SPICE deck through ngspice (KiCad's shared library, driven via PySpice)
and reports the result of its .op / .ac / .tran analysis.
"""

import logging
import os
import sys
import tempfile
import threading

import numpy as np

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


def _plot_svg(ngspice, analysis, nodes, warnings, max_nodes=8):
    """Let ngspice draw the .ac magnitude (dB) / .tran voltage of the nodes as an SVG.

    Returns:
        the SVG markup, or None if there is nothing to draw or the plot failed.
    """
    # flat curves are left out: .ac by magnitude, .tran by the signed voltage
    # (the magnitude of a square wave between -5 V and +5 V would look flat)
    shown = sorted(n for n, data in nodes.items()
                   if np.ptp(np.abs(data) if analysis == "ac" else data.real) > 1e-12)
    if not shown:
        return None
    if len(shown) > max_nodes:
        warnings.append(f"Diagramm zeigt nur die ersten {max_nodes} von {len(shown)} Knoten.")
        shown = shown[:max_nodes]

    func = "vdb" if analysis == "ac" else "v"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plot.svg").replace("\\", "/")
            vectors = " ".join(f'{func}("{n}")' for n in shown)
            for command in ("set hcopydevtype=svg", "set color0=white", "set color1=black",
                            f"hardcopy {path} {vectors}"):
                ngspice.exec_command(command)
            with open(path, encoding="utf-8") as f:
                svg = f.read()
            return svg[svg.find("<svg"):]       
    except Exception as e:
        warnings.append(f"Diagramm konnte nicht erstellt werden: {type(e).__name__}: {e}")
        return None


def run_deck(deck: str) -> dict:
    """Validate a complete SPICE deck and simulate it in ngspice.

    A deck that fails validate_deck is not handed to ngspice at all. 

    Args:
        deck: a runnable SPICE deck.

    Returns:
        dict with:
          success (bool)      - the analysis ran and its vectors were read.
          validation_failed   - True if validate_deck rejected the deck (not run).
          analysis (str)      - 'op' | 'ac' | 'tran', None if nothing ran.
          voltages (dict)     - .op: {node: volts}.
          sweep (dict)        - .ac / .tran: {"axis": frequencies or times,
                                "nodes": {node: values}} (complex for .ac).
          svg (str)           - .ac / .tran: diagram drawn by ngspice, None otherwise.
          errors (list[str])  - validation errors, fatal ngspice messages / exceptions.
          warnings (list[str])- validation warnings and non-fatal ngspice messages.
    """
    out = {"success": False, "validation_failed": False, "analysis": None, "voltages": {},
           "sweep": None, "svg": None, "errors": [], "warnings": []}

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

    from PySpice.Spice.NgSpice.Shared import NgSpiceCommandError, NgSpiceShared

    with _NGSPICE_LOCK:
        collector = _LogCollector()
        pyspice_logger = logging.getLogger("PySpice")
        prev_level = pyspice_logger.level
        pyspice_logger.addHandler(collector)
        pyspice_logger.setLevel(logging.INFO)

        try:
            ngspice = NgSpiceShared.new_instance()
            ngspice.destroy()                  
            ngspice.load_circuit(deck)
            try:
                ngspice.run()
            except NgSpiceCommandError:
                pass

            plot_name = ngspice.last_plot     
            out["analysis"] = plot_name.rstrip("0123456789")
            plot = ngspice.plot(None, plot_name)

            subckts = {l.split()[0].lower() for l in deck.splitlines() if l[:1] in ("X", "x")}
            nodes = {name: np.asarray(vec._data) for name, vec in plot.items()
                     if vec.is_voltage_node and name.split(".")[0] not in subckts}
            
            if out["analysis"] not in ("op", "ac", "tran") or any(d.size == 0 for d in nodes.values()):
                out["analysis"] = None
                raise RuntimeError("ngspice hat keine Simulationsergebnisse geliefert.")
            if out["analysis"] == "op":
                out["voltages"] = {name: float(data[0].real) for name, data in nodes.items()}
            else:
                axis = "frequency" if out["analysis"] == "ac" else "time"
                out["sweep"] = {"axis": np.asarray(plot[axis]._data).real, "nodes": nodes}
                out["svg"] = _plot_svg(ngspice, out["analysis"], nodes, out["warnings"])

            ngspice.remove_circuit()
            out["success"] = True

        except Exception as e:
            out["errors"].append(f"{type(e).__name__}: {e}")
        finally:
            pyspice_logger.removeHandler(collector)
            pyspice_logger.setLevel(prev_level)

    for line in dict.fromkeys(collector.records):
        low = line.lower()
        message = line.split(":", 1)[-1].strip().lower()
        if low.startswith("error") and not message.startswith("note:"):
            out["errors"].append(line)
        elif low.startswith("warning") and "spinit" not in low \
                and "unsupported ngspice" not in low:
            out["warnings"].append(line)

    if out["errors"]:
        out["success"] = False
    return out


def _si(value, unit):
    """Format a number with an SI prefix: (1590, 'Hz') -> '1.59 kHz'."""
    
    value = float(f"{value:.3g}")     
    if abs(value) < 1e-12:
        return f"0 {unit}"
    for factor, prefix in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""),
                           (1e-3, "m"), (1e-6, "µ"), (1e-9, "n")):
        if abs(value) >= factor:
            return f"{value / factor:.3g} {prefix}{unit}"
    return f"{value * 1e12:.3g} p{unit}"


def format_result(result: dict) -> str:
    """Render a run_deck() result as a short human-readable report."""
    sweep = result["sweep"]
    lines = []
    if result["validation_failed"]:
        lines.append("Validierung FEHLGESCHLAGEN - ngspice wurde nicht gestartet.")
    elif not result["success"]:
        lines.append("Simulation FEHLGESCHLAGEN.")
    elif result["analysis"] == "ac":
        lines.append(f"Simulation OK (Frequenzgang {_si(sweep['axis'][0], 'Hz')} - "
                     f"{_si(sweep['axis'][-1], 'Hz')}).")
    elif result["analysis"] == "tran":
        lines.append(f"Simulation OK (Zeitverlauf {_si(sweep['axis'][0], 's')} - "
                     f"{_si(sweep['axis'][-1], 's')}, {len(sweep['axis'])} Punkte).")
    else:
        lines.append("Simulation OK (Arbeitspunkt gelöst).")

    if result["voltages"]:
        lines.append("")
        lines.append("Knotenspannungen:")
        for node, v in sorted(result["voltages"].items()):
            lines.append(f"  {node} = {v:.4g} V")

    if sweep and result["analysis"] == "ac":
        freqs = sweep["axis"]
        decades = 10.0 ** np.arange(np.ceil(np.log10(freqs[0])), np.log10(freqs[-1]) + 1e-9)
        lines += ["", "Frequenzgang (Betrag / Phase):"]

        for node, values in sorted(sweep["nodes"].items()):
            mag = np.abs(values)
            if not mag.any():
                lines.append(f"  {node}: kein AC-Anteil")
                continue

            db = 20 * np.log10(np.maximum(mag, 1e-30))
            below = np.nonzero(db < db[0] - 3)[0]

            corner = ""
            if below.size and below[0] > 0:
                i = below[0]

                lf = np.interp(db[0] - 3, [db[i], db[i - 1]], np.log10([freqs[i], freqs[i - 1]]))
                corner = f"  (-3 dB bei {_si(10 ** lf, 'Hz')})"
            lines.append(f"  {node}{corner}")
            
            for f in decades:
                i = int(np.argmin(np.abs(np.log10(freqs) - np.log10(f))))
                lines.append(f"      {_si(freqs[i], 'Hz'):>9}  {db[i]:7.1f} dB  "
                             f"{np.angle(values[i], deg=True):7.1f}°")

    if sweep and result["analysis"] == "tran":
        lines += ["", "Zeitverlauf (min / max / Ende):"]
        for node, values in sorted(sweep["nodes"].items()):
            values = values.real
            lines.append(f"  {node}: min {_si(values.min(), 'V')}, max {_si(values.max(), 'V')}, "
                         f"Ende {_si(values[-1], 'V')}")

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
