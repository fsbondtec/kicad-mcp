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
          currents (dict)     - .op / .tran: {ngspice vector name: amperes} of the top-level
                                elements, sorted, without zero currents.
          svg (str)           - .ac / .tran: diagram drawn by ngspice, None otherwise.
          errors (list[str])  - validation errors, fatal ngspice messages / exceptions.
          warnings (list[str])- validation warnings and non-fatal ngspice messages.
    """
    out = {"success": False, "validation_failed": False, "analysis": None, "voltages": {},
           "sweep": None, "currents": {}, "svg": None, "errors": [], "warnings": []}

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
            nodes = {name: np.array(vec.to_waveform()) for name, vec in plot.items()
                     if vec.is_voltage_node and name.split(".")[0] not in subckts}
            
            if out["analysis"] not in ("op", "ac", "tran") or any(d.size == 0 for d in nodes.values()):
                out["analysis"] = None
                raise RuntimeError("ngspice hat keine Simulationsergebnisse geliefert.")
            if out["analysis"] == "op":
                out["voltages"] = {name: float(data[0].real) for name, data in nodes.items()}
            else:
                axis = "frequency" if out["analysis"] == "ac" else "time"
                out["sweep"] = {"axis": np.array(plot[axis].to_waveform()).real, "nodes": nodes}
                out["svg"] = _plot_svg(ngspice, out["analysis"], nodes, out["warnings"])
            if out["analysis"] != "ac":
                currents = {name: np.array(vec.to_waveform()).real for name, vec in plot.items()
                            if (name.startswith("@") or vec.is_branch_current) and "." not in name}
                out["currents"] = {name: data for name, data in sorted(currents.items())
                                   if data.size and np.abs(data).max() > 1e-12}

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


def _si(value, unit, digits=3):
    """Format a number with an SI prefix: (1590, 'Hz') -> '1.59 kHz'."""

    value = float(f"{value:.{digits}g}")
    if abs(value) < 1e-12:
        return f"0 {unit}"
    for factor, prefix in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""),
                           (1e-3, "m"), (1e-6, "µ"), (1e-9, "n")):
        if abs(value) >= factor:
            return f"{value / factor:.{digits}g} {prefix}{unit}"
    return f"{value * 1e12:.{digits}g} p{unit}"


def _summary(result):
    """One-line status of a run_deck() result."""
    sweep = result["sweep"]
    if result["validation_failed"]:
        return "Validierung FEHLGESCHLAGEN - ngspice wurde nicht gestartet."
    if not result["success"]:
        return "Simulation FEHLGESCHLAGEN."
    if result["analysis"] == "ac":
        return (f"Simulation OK (Frequenzgang {_si(sweep['axis'][0], 'Hz')} - "
                f"{_si(sweep['axis'][-1], 'Hz')}).")
    if result["analysis"] == "tran":
        return (f"Simulation OK (Zeitverlauf {_si(sweep['axis'][0], 's')} - "
                f"{_si(sweep['axis'][-1], 's')}, {len(sweep['axis'])} Punkte).")
    return "Simulation OK (Arbeitspunkt gelöst)."


def _corner_frequency(freqs, db):
    """Frequency where the magnitude first falls 3 dB below its start value, or None."""
    below = np.nonzero(db < db[0] - 3)[0]
    if not below.size or below[0] == 0:
        return None
    i = below[0]
    return 10 ** np.interp(db[0] - 3, [db[i], db[i - 1]], np.log10([freqs[i], freqs[i - 1]]))


def result_tables(result: dict, deck: str) -> dict:
    """Render a run_deck() result as table rows for the UI.
    Returns:
        {"status": 'ok' | 'failed' | 'invalid', "summary": one-line status,
         "voltages": [row], "currents": [row], "errors": [...], "warnings": [...]};
        the row keys depend on the analysis (.op value, .tran min/max/end/eff,
        .ac corner/gain/phase).
    """
    spelling = {token.lower(): token for line in deck.splitlines() if line[:1].isalpha()
                for token in line.split()}
    name = lambda node: spelling.get(node, node)
    analysis = result["analysis"]
    sweep = result["sweep"]

    voltages = []
    if result["voltages"]:
        for node, v in sorted(result["voltages"].items()):
            voltages.append({"name": name(node), "value": _si(v, "V", digits=4)})
    elif sweep and analysis == "tran":
        for node, values in sorted(sweep["nodes"].items()):
            values = values.real
            voltages.append({"name": name(node), "min": _si(values.min(), "V"),
                             "max": _si(values.max(), "V"), "end": _si(values[-1], "V")})
    elif sweep and analysis == "ac":
        freqs = sweep["axis"]
        for node, values in sorted(sweep["nodes"].items()):
            if not np.abs(values).any():
                voltages.append({"name": name(node), "corner": "-", "gain": "kein AC-Anteil",
                                 "phase": "-"})
                continue
            db = 20 * np.log10(np.maximum(np.abs(values), 1e-30))
            corner = _corner_frequency(freqs, db)
            voltages.append({"name": name(node),
                             "corner": _si(corner, "Hz") if corner else "-",
                             "gain": f"{db[-1]:.1f} dB",
                             "phase": f"{np.angle(values[-1], deg=True):.1f}°"})

    currents = []
    for vector, current in result["currents"].items():
        if vector.endswith("#branch"):
            label = name(vector[:-len("#branch")])
        else:
            element, _, terminal = vector[1:].rstrip("]").partition("[")
            label = name(element) if terminal == "i" else f"{name(element)} {terminal}"
        if analysis == "tran":
            time = sweep["axis"]
            rms = np.sqrt(np.trapezoid(current ** 2, time) / (time[-1] - time[0]))
            currents.append({"name": label, "max": _si(np.abs(current).max(), "A"),
                             "eff": _si(rms, "A")})
        else:
            currents.append({"name": label, "value": _si(current[0], "A")})

    if result["validation_failed"]:
        status = "invalid"
    elif result["success"]:
        status = "ok"
    else:
        status = "failed"
    return {"status": status, "summary": _summary(result), "voltages": voltages,
            "currents": currents, "errors": result["errors"], "warnings": result["warnings"]}


def _format_currents(result):
    """Report lines for the currents: .op value, .tran peak and RMS."""
    currents = result["currents"]
    if not currents:
        return []

    lines = ["", "Ströme (positiv = in den Anschluss hinein; negativer Quellenstrom = Quelle liefert):"]
    for name, current in currents.items():
        if result["analysis"] == "tran":
            time = result["sweep"]["axis"]
            rms = np.sqrt(np.trapezoid(current ** 2, time) / (time[-1] - time[0]))
            lines.append(f"  {name}: max {_si(np.abs(current).max(), 'A')}, eff {_si(rms, 'A')}")
        else:
            lines.append(f"  {name} = {_si(current[0], 'A')}")
    return lines


def format_result(result: dict) -> str:
    """Render a run_deck() result as a short human-readable report."""
    sweep = result["sweep"]
    lines = [_summary(result)]

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
            if not np.abs(values).any():
                lines.append(f"  {node}: kein AC-Anteil")
                continue

            db = 20 * np.log10(np.maximum(np.abs(values), 1e-30))
            corner = _corner_frequency(freqs, db)
            lines.append(f"  {node}" + (f"  (-3 dB bei {_si(corner, 'Hz')})" if corner else ""))

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

    lines += _format_currents(result)

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
