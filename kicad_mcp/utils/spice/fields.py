"""
Form fields of the SPICE simulation UI: their definition, the check of the entered
values and the conversion into SPICE text (analysis directive, source spec, port value).
"""

from kicad_mcp.utils.spice.deck import MEGA_M_RE, SPICE_VALUE_RE, spice_float


ANALYSIS_DEFAULTS = {
    "analysis": ".op",
    "ac_sweep": "dec", "ac_points": "20", "ac_fstart": "1", "ac_fstop": "1Meg",
    "tran_step": "1u", "tran_stop": "5m", "tran_start": "", "tran_max": "", "tran_uic": False,
}

SOURCE_FIELDS = {
    "DC": [("dc", "Spannung", "5")],
    "PULSE": [("v1", "Low", "0"), ("v2", "High", "5"), ("td", "Verzögerung", "0"),
              ("tr", "Anstieg", "1u"), ("tf", "Abfall", "1u"), ("pw", "Pulsbreite", "50u"),
              ("per", "Periode", "100u")],
    "SIN": [("vo", "Offset", "0"), ("va", "Amplitude", "1"), ("freq", "Frequenz", "1k"),
            ("sin_td", "Verzögerung", "optional")],
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

    fields = []
    if analysis.get("analysis") == ".ac":
        fields.append(("Analyse, Punkte", analysis.get("ac_points"), True))
        fields.append(("Analyse, Startfrequenz", analysis.get("ac_fstart"), True))
        fields.append(("Analyse, Stoppfrequenz", analysis.get("ac_fstop"), True))
    elif analysis.get("analysis") == ".tran":
        fields.append(("Analyse, Schrittweite", analysis.get("tran_step"), True))
        fields.append(("Analyse, Endzeit", analysis.get("tran_stop"), True))
        fields.append(("Analyse, Startzeit", analysis.get("tran_start"), False))
        fields.append(("Analyse, Max. Schritt", analysis.get("tran_max"), False))

    errors = []
    sources = []
    for number, port in enumerate(ports or [], start=1):
        where = f"Port {number} ({port['net']})"
        if port.get("role") == "input":
            sources.append((where, port.get("source") or {}, True))
        elif port.get("role") == "load":
            fields.append((f"{where}, Wert", port.get("load_value"), True))
    for supply in supplies or []:
        sources.append((f"Versorgung {supply['net']}", supply.get("source") or {}, False))

    for where, source, needs_value in sources:
        kind = source.get("type") or "DC"
        source_fields = [(label, source.get(key)) for key, label, _ in SOURCE_FIELDS[kind]]
        source_fields.append(("AC-Amplitude", source.get("ac")))

        has_value = False
        for label, value in source_fields:
            fields.append((f"{where}, {label}", value, False))
            if str(value or "").strip():
                has_value = True
        if needs_value and not has_value:
            errors.append(f"{where}: keine Quellwerte eingetragen.")

    for where, value, required in fields:
        text = str(value or "").strip()
        if not text:
            if required:
                errors.append(f"{where}: Feld ist leer.")
        elif "," in text:
            errors.append(f"{where}: '{text}' - Punkt statt Komma verwenden.")
        elif not SPICE_VALUE_RE.match(text):
            errors.append(f"{where}: '{text}' ist keine SPICE-Zahl (z. B. 1u, 4.7k, 1Meg).")
        elif MEGA_M_RE.match(text):
            errors.append(f"{where}: '{text}' - M bedeutet in SPICE Milli. Fuer Mega 'Meg' "
                          "schreiben (1Meg), fuer Milli 'm' (1m).")

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
            errors.append("Analyse, Punkte: mindestens 1.")
        if fstart <= 0 and a.get("ac_sweep") != "lin":
            errors.append("Analyse, Startfrequenz: muss bei dec/oct groesser als 0 sein.")
        if fstop <= fstart:
            errors.append("Analyse, Stoppfrequenz: muss groesser als die Startfrequenz sein.")
    elif a.get("analysis") == ".tran":
        step, stop, start, tmax = (num("tran_step"), num("tran_stop"), num("tran_start"),
                                   num("tran_max"))
        if step <= 0:
            errors.append("Analyse, Schrittweite: muss groesser als 0 sein.")
        if stop <= 0:
            errors.append("Analyse, Endzeit: muss groesser als 0 sein.")
        elif step > stop:
            errors.append("Analyse, Schrittweite: groesser als die Endzeit.")
        if start is not None and not 0 <= start < stop:
            errors.append("Analyse, Startzeit: muss zwischen 0 und der Endzeit liegen.")
        if tmax is not None and tmax <= 0:
            errors.append("Analyse, Max. Schritt: muss groesser als 0 sein.")
    return errors


def port_value(port: dict) -> str:
    """SPICE value of a port: source text for input, the part value ('10k') for load,
    '' for output."""
    if port.get("role") == "input":
        return source_spec(port.get("source") or {})
    if port.get("role") == "load":
        return str(port.get("load_value") or "").strip()
    return ""
