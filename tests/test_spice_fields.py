import pytest

from kicad_mcp.utils.spice.fields import (
    ANALYSIS_DEFAULTS,
    analysis_line,
    check_fields,
    port_value,
    source_spec,
)


def _analysis(**fields):
    """UI analysis fields: the defaults of the form, overridden by fields."""
    return {**ANALYSIS_DEFAULTS, **fields}


def _source(**fields):
    return {"type": "DC", "dc": "", "ac": "", **fields}


class TestAnalysisLine:
    def test_operating_point_is_default(self):
        assert analysis_line(_analysis()) == ".op"

    def test_ac(self):
        assert analysis_line(_analysis(analysis=".ac")) == ".ac dec 20 1 1Meg"

    def test_ac_lin(self):
        line = analysis_line(_analysis(analysis=".ac", ac_sweep="lin", ac_points="100",
                                       ac_fstart="0", ac_fstop="10k"))

        assert line == ".ac lin 100 0 10k"

    def test_tran(self):
        assert analysis_line(_analysis(analysis=".tran")) == ".tran 1u 5m"

    def test_tran_max_step_gets_start_zero(self):
        """ngspice reads the third value as start time, so it must be there before the max step."""
        assert analysis_line(_analysis(analysis=".tran", tran_max="10n")) == ".tran 1u 5m 0 10n"

    def test_tran_start_and_uic(self):
        line = analysis_line(_analysis(analysis=".tran", tran_start="1m", tran_uic=True))

        assert line == ".tran 1u 5m 1m uic"


class TestSourceSpec:
    def test_dc(self):
        assert source_spec(_source(dc="5")) == "DC 5"

    def test_dc_and_ac(self):
        assert source_spec(_source(dc="5", ac="1")) == "DC 5 AC 1"

    def test_ac_only(self):
        assert source_spec(_source(ac="1")) == "AC 1"

    def test_pulse(self):
        source = _source(type="PULSE", v1="0", v2="5", td="0", tr="1u", tf="1u", pw="50u", per="100u")

        assert source_spec(source) == "PULSE(0 5 0 1u 1u 50u 100u)"

    def test_trailing_optional_value_dropped(self):
        assert source_spec(_source(type="SIN", vo="0", va="1", freq="1k", sin_td="")) == "SIN(0 1 1k)"

    def test_empty_value_in_between_becomes_zero(self):
        assert source_spec(_source(type="SIN", vo="", va="1", freq="1k")) == "SIN(0 1 1k)"


class TestPortValue:
    def test_input_is_source_spec(self):
        assert port_value({"role": "input", "source": _source(dc="5")}) == "DC 5"

    def test_load_is_part_value(self):
        assert port_value({"role": "load", "load_value": " 10k "}) == "10k"

    def test_output_has_no_value(self):
        assert port_value({"role": "output"}) == ""


class TestCheckFields:
    def test_valid_input(self):
        ports = [{"net": "/in", "role": "input", "source": _source(dc="1", ac="1")},
                 {"net": "/out", "role": "load", "load_value": "10k"}]

        assert check_fields(_analysis(analysis=".ac"), ports, []) == []

    def test_input_without_values(self):
        errors = check_fields(_analysis(), [{"net": "/in", "role": "input", "source": _source()}], [])

        assert errors == ["Port 1 (/in): keine Quellwerte eingetragen."]

    def test_supply_may_stay_empty(self):
        assert check_fields(_analysis(), [], [{"net": "+5V", "source": _source()}]) == []

    def test_load_without_value(self):
        errors = check_fields(_analysis(), [{"net": "/out", "role": "load", "load_value": ""}], [])

        assert errors == ["Port 1 (/out), Wert: Feld ist leer."]

    def test_comma_instead_of_point(self):
        errors = check_fields(_analysis(), [{"net": "/out", "role": "load", "load_value": "4,7k"}], [])

        assert errors == ["Port 1 (/out), Wert: '4,7k' - Punkt statt Komma verwenden."]

    def test_no_spice_number(self):
        errors = check_fields(_analysis(), [{"net": "/out", "role": "load", "load_value": "abc"}], [])

        assert any("'abc' ist keine SPICE-Zahl" in e for e in errors)

    @pytest.mark.parametrize("value", ["1M", "1MHz"])
    def test_capital_m_rejected(self, value):
        """SPICE reads M as milli, a load of '1M' would be 1 milliohm."""
        errors = check_fields(_analysis(), [{"net": "/out", "role": "load", "load_value": value}], [])

        assert any("M bedeutet in SPICE Milli" in e for e in errors)

    def test_required_analysis_field_empty(self):
        errors = check_fields(_analysis(analysis=".ac", ac_points=""), [], [])

        assert errors == ["Analyse, Punkte: Feld ist leer."]

    def test_fields_of_other_analysis_ignored(self):
        assert check_fields(_analysis(analysis=".op", ac_points="", tran_step="x"), [], []) == []

    def test_tran_step_larger_than_stop(self):
        errors = check_fields(_analysis(analysis=".tran", tran_step="1m", tran_stop="1u"), [], [])

        assert errors == ["Analyse, Schrittweite: groesser als die Endzeit."]

    def test_tran_start_after_stop(self):
        errors = check_fields(_analysis(analysis=".tran", tran_start="10m"), [], [])

        assert errors == ["Analyse, Startzeit: muss zwischen 0 und der Endzeit liegen."]

    def test_ac_start_zero_needs_lin(self):
        errors = check_fields(_analysis(analysis=".ac", ac_fstart="0"), [], [])

        assert errors == ["Analyse, Startfrequenz: muss bei dec/oct groesser als 0 sein."]

    def test_ac_lin_may_start_at_zero(self):
        assert check_fields(_analysis(analysis=".ac", ac_sweep="lin", ac_fstart="0"), [], []) == []

    def test_ac_stop_not_above_start(self):
        errors = check_fields(_analysis(analysis=".ac", ac_fstart="1k", ac_fstop="100"), [], [])

        assert errors == ["Analyse, Stoppfrequenz: muss groesser als die Startfrequenz sein."]
