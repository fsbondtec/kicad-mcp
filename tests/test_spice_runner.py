import numpy as np
import pytest

from kicad_mcp.utils.cli_drc import find_kicad_cli
from kicad_mcp.utils.spice import runner
from kicad_mcp.utils.spice.runner import (
    _HARMLESS_RE,
    _passband,
    _si,
    format_result,
    result_tables,
    run_deck,
)

needs_ngspice = pytest.mark.skipif(find_kicad_cli() is None,
                                   reason="kicad-cli / ngspice of KiCad not installed")


def _deck(*lines):
    return "\n".join([".title test", *lines, ".end"])


def _ac_result(freqs, values):
    """run_deck() result of an .ac run with one node 'out'."""
    return {"success": True, "validation_failed": False, "analysis": "ac", "voltages": {},
            "sweep": {"axis": np.asarray(freqs, dtype=float),
                      "nodes": {"out": np.asarray(values, dtype=complex)}},
            "currents": {}, "svg": None, "errors": [], "warnings": []}


def _db(h):
    return 20 * np.log10(np.abs(h))


FREQS = np.logspace(0, 7, 701)       


class TestSi:
    @pytest.mark.parametrize("value, unit, expected", [
        (1591.5, "Hz", "1.59 kHz"),
        (0.0025, "A", "2.5 mA"),
        (4.7e-12, "F", "4.7 pF"),
        (2.2e6, "Hz", "2.2 MHz"),
        (12, "V", "12 V"),
        (0, "V", "0 V"),
        (-0.69, "V", "-690 mV"),
    ])
    def test_si_prefix(self, value, unit, expected):
        assert _si(value, unit) == expected


class TestPassband:
    def test_lowpass(self):
        h = 1 / (1 + 1j * FREQS / 1591.5)

        assert _passband(FREQS, _db(h)) == "up to 1.59 kHz"

    def test_highpass(self):
        """3 dB below the maximum is at 1595 Hz (exactly 3 dB, not 3.01 dB = 1/sqrt(2))."""
        x = 1j * FREQS / 1591.5
        h = x / (1 + x)

        assert _passband(FREQS, _db(h)) == "from 1.6 kHz"

    def test_bandpass(self):
        """Poles two decades apart: the maximum is -0.086 dB, the edges are measured from it."""
        x = 1j * FREQS / 159.15
        h = x / (1 + x) / (1 + 1j * FREQS / 15915)

        assert _passband(FREQS, _db(h)) == "156 Hz - 16.2 kHz"

    def test_sweep_starting_above_corner_has_no_passband(self):
        """The first sweep point is already 3 dB down; it must not serve as reference."""
        freqs = np.logspace(4, 7, 301)

        assert _passband(freqs, _db(1 / (1 + 1j * freqs / 1591.5))) is None

    def test_flat_response(self):
        assert _passband(FREQS, np.zeros_like(FREQS)) is None

    def test_lin_sweep_from_zero(self):
        freqs = np.linspace(0, 20e3, 201)

        assert _passband(freqs, _db(1 / (1 + 1j * freqs / 1591.5))) == "up to 1.59 kHz"


class TestHarmlessNotes:
    @pytest.mark.parametrize("message", [
        "unrecognized parameter (iave) - ignored",
        "unrecognized parameter (bvcbo) - ignored",
        ".model laser d(is=1e-22 rs=6 n=1.5 iave=160m vpk=5) ...",
    ])
    def test_ignored_model_parameters(self, message):
        assert _HARMLESS_RE.match(message)

    @pytest.mark.parametrize("message", [
        "warning, can't find model 'nomodel' from line",
        "doanalyses: tran:  timestep too small; time = 1e-10",
        "error: circuit not parsed.",
        "mif-error - unable to find definition of model a$poly$e.xu1.eos",
    ])
    def test_real_errors(self, message):
        assert not _HARMLESS_RE.match(message)


class TestReports:
    def test_ac_report_with_zero_hz(self):
        """.ac lin may start at 0 Hz; the decade rows must not take log10(0)."""
        result = _ac_result([0, 500, 1000], [1, 0.95, 0.85])

        report = format_result(result)

        assert "frequency response 0 Hz - 1 kHz" in report
        assert "1 kHz" in report

    def test_ac_table(self):
        h = 1 / (1 + 1j * FREQS / 1591.5)

        rows = result_tables(_ac_result(FREQS, h), _deck("R1 in out 1k"))["voltages"]

        assert rows == [{"name": "out", "corner": "up to 1.59 kHz", "gain": "-76.0 dB", "phase": "-90.0°"}]

    def test_node_names_spelled_as_in_deck(self):
        """ngspice writes node names in lower case, the tables use the deck's spelling."""
        result = {"success": True, "validation_failed": False, "analysis": "op",
                  "voltages": {"net-_d1-a_": 1.0}, "sweep": None, "currents": {}, "svg": None,
                  "errors": [], "warnings": []}

        rows = result_tables(result, _deck("V1 Net-_D1-A_ 0 DC 1"))["voltages"]

        assert rows == [{"name": "Net-_D1-A_", "value": "1 V"}]

    def test_status(self):
        failed = {"success": False, "validation_failed": True, "analysis": None, "voltages": {},
                  "sweep": None, "currents": {}, "svg": None, "errors": ["x"], "warnings": []}

        tables = result_tables(failed, "")

        assert tables["status"] == "invalid"
        assert "ngspice was not started" in tables["summary"]


@pytest.mark.requires_kicad
@needs_ngspice
class TestRunDeck:
    def test_divider_operating_point(self):
        result = run_deck(_deck("V1 in 0 DC 5", "R1 in out 1k", "R2 out 0 1k", ".op"))

        assert result["success"] is True
        assert result["voltages"]["out"] == pytest.approx(2.5)
        assert result["currents"]["v1#branch"][0] == pytest.approx(-2.5e-3)

    def test_invalid_deck_not_run(self):
        result = run_deck(_deck("R1 a 0 1k", ".op"))

        assert result["validation_failed"] is True
        assert result["analysis"] is None

    def test_lowpass_frequency_response(self):
        result = run_deck(_deck("V1 in 0 DC 0 AC 1", "R1 in out 1k", "C1 out 0 100n",
                                ".ac dec 20 1 1Meg"))

        rows = {r["name"]: r for r in result_tables(result, "")["voltages"]}
        assert result["success"] is True
        assert rows["out"]["corner"] == "up to 1.59 kHz"
        assert result["svg"]

    def test_transient(self):
        result = run_deck(_deck("V1 in 0 PULSE(0 1 0 1u 1u 1m 2m)", "R1 in out 1k", "C1 out 0 100n",
                                ".tran 1u 4m"))

        assert result["success"] is True
        assert result["sweep"]["nodes"]["out"].real.max() == pytest.approx(1.0, abs=0.01)

    def test_ac_lin_from_zero_hz(self):
        result = run_deck(_deck("V1 in 0 DC 0 AC 1", "R1 in out 1k", "C1 out 0 100n",
                                ".ac lin 10 0 1k"))

        assert result["success"] is True
        assert "frequency response 0 Hz - 1 kHz" in format_result(result)

    def test_ignored_model_parameter_is_a_warning(self):
        """PSpice extras like vpk are skipped by ngspice, the result stays valid."""
        result = run_deck(_deck(".model dx d(is=1e-14 vpk=5)", "V1 in 0 DC 5", "R1 in out 1k",
                                "D1 out 0 dx", ".op"))

        assert result["success"] is True
        assert result["errors"] == []
        assert any("unrecognized parameter (vpk)" in w for w in result["warnings"])

    def test_missing_model_is_an_error(self):
        result = run_deck(_deck("V1 in 0 DC 5", "R1 in out 1k", "D1 out 0 nomodel", ".op"))

        assert result["success"] is False
        assert any("nomodel" in e for e in result["errors"])

    def test_poly_source_needs_code_models(self, tmp_path):
        """POLY sources of vendor models are translated into an XSPICE code model."""
        lib = tmp_path / "amp.lib"
        lib.write_text(".subckt amp in out\nE1 out 0 POLY(1) in 0 0 2\n.ends\n")

        result = run_deck(_deck(f'.include "{lib.as_posix()}"', "V1 in 0 DC 1", "X1 in out amp",
                                "R1 out 0 1k", ".op"))

        assert result["success"] is True, result["errors"]
        assert result["voltages"]["out"] == pytest.approx(2.0)

    def test_ngspice_usable_after_unrecoverable_error(self):
        """A syntax error leaves ngspice waiting for a reset; the next deck must still run."""
        broken = run_deck(_deck(".model dx d(is=1e-14 rs=)", "V1 in 0 DC 5", "R1 in out 1k",
                                "D1 out 0 dx", ".op"))
        good = run_deck(_deck("V1 in 0 DC 5", "R1 in out 1k", "R2 out 0 1k", ".op"))

        assert broken["success"] is False
        assert any("was reloaded" in w for w in broken["warnings"])
        assert good["success"] is True
        assert runner._code_models_loaded is True
