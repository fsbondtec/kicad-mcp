"""
Form fields of the SPICE simulation UI: their definition, the check of the entered
values and the conversion into SPICE text (analysis directive, source spec, port value).
"""

from kicad_mcp.utils.spice.deck import MEGA_M_RE, SPICE_VALUE_RE, spice_float


# number fields of each analysis: (key, label, example), 'optional' = not required, starts empty
ANALYSIS_FIELDS = {
    ".ac": [("ac_points", "Points", "20"), ("ac_fstart", "Start frequency", "1"),
            ("ac_fstop", "Stop frequency", "1Meg")],
    ".tran": [("tran_step", "Step", "1u"), ("tran_stop", "Stop time", "5m"),
              ("tran_start", "Start time", "optional"), ("tran_max", "Max. step", "optional")],
}
ANALYSIS_DEFAULTS = {"analysis": ".op", "ac_sweep": "dec", "tran_uic": False,
                     **{key: "" if example == "optional" else example
                        for fields in ANALYSIS_FIELDS.values() for key, _, example in fields}}

SOURCE_FIELDS = {
    "DC": [("dc", "Voltage", "5")],
    "PULSE": [("v1", "Low", "0"), ("v2", "High", "5"), ("td", "Delay", "0"),
              ("tr", "Rise time", "1u"), ("tf", "Fall time", "1u"), ("pw", "Pulse width", "50u"),
              ("per", "Period", "100u")],
    "SIN": [("vo", "Offset", "0"), ("va", "Amplitude", "1"), ("freq", "Frequency", "1k"),
            ("sin_td", "Delay", "optional")],
}
SOURCE_KEYS = ["type", "ac"] + [key for fields in SOURCE_FIELDS.values() for key, _, _ in fields]


def analysis_line(a: dict) -> str:
    """Build the analysis directive from the UI fields, e.g. '.ac dec 20 1 1Meg'."""
    v = lambda key: str(a.get(key) or "").strip()
    if v("analysis") == ".ac":
        return f".ac {v('ac_sweep')} {v('ac_points')} {v('ac_fstart')} {v('ac_fstop')}"
    if v("analysis") == ".tran":
        parts = [".tran", v("tran_step"), v("tran_stop")]
        if v("tran_start") or v("tran_max"):
            parts.append(v("tran_start") or "0")
        if v("tran_max"):
            parts.append(v("tran_max"))
        if a.get("tran_uic"):
            parts.append("uic")
        return " ".join(parts)
    return ".op"


def source_spec(source: dict) -> str:
    """Build the SPICE source text from the UI fields, e.g. 'PULSE(0 5 0 1u 1u 50u 100u) AC 1'.
    """
    v = lambda key: str(source.get(key) or "").strip()
    kind = v("type") or "DC"
    values = [v(key) for key, _, _ in SOURCE_FIELDS[kind]]
    while values and not values[-1]:
        values.pop()

    parts = []
    if values:
        values = [value or "0" for value in values]
        parts.append(f"DC {values[0]}" if kind == "DC" else f"{kind}({' '.join(values)})")
    if v("ac"):
        parts.append(f"AC {v('ac')}")
    return " ".join(parts)


def check_fields(analysis: dict, ports: list, supplies: list) -> list:
    """Check the UI input fields before anything is built from them.

    Every filled field must be a SPICE number; the analysis parameters, the value of a
    load and at least one value of an input source are required. Only the fields of the
    selected analysis and source type are checked.

    Returns:
        list of error messages naming the field, empty if everything is fine.
    """

    fields = [(f"Analysis, {label}", analysis.get(key), example != "optional")
              for key, label, example in ANALYSIS_FIELDS.get(analysis.get("analysis"), [])]

    errors = []
    sources = []
    for number, port in enumerate(ports or [], start=1):
        where = f"Port {number} ({port['net']})"
        if port.get("role") == "input":
            sources.append((where, port.get("source") or {}, True))
        elif port.get("role") == "load":
            fields.append((f"{where}, value", port.get("load_value"), True))
    for supply in supplies or []:
        sources.append((f"Supply {supply['net']}", supply.get("source") or {}, False))

    for where, source, needs_value in sources:
        kind = source.get("type") or "DC"
        source_fields = [(label, source.get(key)) for key, label, _ in SOURCE_FIELDS[kind]]
        source_fields.append(("AC amplitude", source.get("ac")))

        has_value = False
        for label, value in source_fields:
            fields.append((f"{where}, {label}", value, False))
            if str(value or "").strip():
                has_value = True
        if needs_value and not has_value:
            errors.append(f"{where}: no source values entered.")

    for where, value, required in fields:
        text = str(value or "").strip()
        if not text:
            if required:
                errors.append(f"{where}: field is empty.")
        elif "," in text:
            errors.append(f"{where}: '{text}' - use a point instead of a comma.")
        elif not SPICE_VALUE_RE.match(text):
            errors.append(f"{where}: '{text}' is not a SPICE number (e.g. 1u, 4.7k, 1Meg).")
        elif MEGA_M_RE.match(text):
            errors.append(f"{where}: '{text}' - M means milli in SPICE. Write 'Meg' for mega "
                          "(1Meg), 'm' for milli (1m).")

    # check numbers make a runnable analysis
    if not errors:
        errors += _range_errors(analysis)
    return errors


def _range_errors(a: dict) -> list:
    """Analysis values ngspice cannot run: zero or negative times, start after stop."""
    def num(key):
        text = str(a.get(key) or "").strip()
        return spice_float(text) if text else None

    errors = []
    if a.get("analysis") == ".ac":
        points, fstart, fstop = num("ac_points"), num("ac_fstart"), num("ac_fstop")
        if points < 1:
            errors.append("Analysis, Points: at least 1.")
        if fstart <= 0 and a.get("ac_sweep") != "lin":
            errors.append("Analysis, Start frequency: must be greater than 0 for dec/oct.")
        if fstop <= fstart:
            errors.append("Analysis, Stop frequency: must be greater than the start frequency.")
    elif a.get("analysis") == ".tran":
        step, stop, start, tmax = (num("tran_step"), num("tran_stop"), num("tran_start"),
                                   num("tran_max"))
        if step <= 0:
            errors.append("Analysis, Step: must be greater than 0.")
        if stop <= 0:
            errors.append("Analysis, Stop time: must be greater than 0.")
        elif step > stop:
            errors.append("Analysis, Step: greater than the stop time.")
        if start is not None and not 0 <= start < stop:
            errors.append("Analysis, Start time: must be between 0 and the stop time.")
        if tmax is not None and tmax <= 0:
            errors.append("Analysis, Max. step: must be greater than 0.")
    return errors


def port_value(port: dict) -> str:
    """SPICE value of a port: source text for input, the part value ('10k') for load,
    '' for output."""
    if port.get("role") == "input":
        return source_spec(port.get("source") or {})
    if port.get("role") == "load":
        return str(port.get("load_value") or "").strip()
    return ""
