import pytest

from kicad_mcp.utils.spice.deck import (
    SpiceNetlistParser,
    build_isolated_deck,
    build_net_node_map,
    element_ref,
    node_count,
    part_value,
    spice_float,
    validate_deck,
)

SAMPLE_EXPORT = """.title KiCad schematic
.model __D1 D
.options reltol=1e-4
.temp 50
.tran 1u 10m
.probe V(/out)
.ic V(/out)=2 V(/far)=1 V(GND)=0
.ic I(L1)=1m
.control
set controlswait
run
.endc
K1 L1 L2 0.98
K2 L1 L9 0.5
K3 L8 L9 0.5
Rmix /out GND 200
V1 /in GND DC 5
R1 /in /out 1k
L1 /out GND 1m
L2 /sec GND 1m
R2 /sec GND 1k
D1 /out GND __D1
R9 /far GND 1k
.end
"""

BLOCK = ["V1", "R1", "L1", "L2", "R2", "D1"]
SCHEMATIC_REFS = BLOCK + ["R9"]


def _parsed(text=SAMPLE_EXPORT):
    sp = SpiceNetlistParser(text)
    sp.parse()
    return sp


def _deck(*lines):
    return "\n".join([".title test", *lines, ".end"])


def _element(line):
    tokens = line.split()
    return {"name": tokens[0], "tokens": tokens, "raw": line}


class TestPartValue:
    @pytest.mark.parametrize("value, expected", [
        ("4k7", "4.7k"),
        ("5k6;1W", "5.6k"),
        ("1R5", "1.5"),
        ("R47", "0.47"),
        ("2M2", "2.2Meg"),
        ("1M", "1Meg"),
        ("1Meg", "1Meg"),
        ("2200uF;63V", "2200uF"),
        ("10k/1%", "10k"),
        ("4.7µF", "4.7uF"),
        ("100n", "100n"),
        ("1m", "1m"),
    ])
    def test_value_field_to_spice_number(self, value, expected):
        assert part_value(value) == expected


class TestSpiceFloat:
    @pytest.mark.parametrize("text, expected", [
        ("4.7k", 4700.0),
        ("1Meg", 1e6),
        ("100nF", 1e-7),
        ("1e-6", 1e-6),
        ("1m", 1e-3),
        ("10", 10.0),
    ])
    def test_scale_factors(self, text, expected):
        assert spice_float(text) == pytest.approx(expected)


class TestNodeCount:
    @pytest.mark.parametrize("line, expected", [
        ("R1 a b 1k", 2),
        ("V1 a 0 DC 5 AC 1", 2),
        ("B1 a 0 V=V(b)*2", 2),
        ("Q1 c b e QMOD", 3),
        ("MQ2 d g s __Q2", 3),
        ("XU1 in out vcc vee OPAMP", 4),
        ("K1 L1 L2 0.98", 0),
    ])
    def test_nodes_of_element_line(self, line, expected):
        assert node_count(line.split()) == expected


class TestElementRef:
    def test_exact_reference(self):
        assert element_ref("R1", {"R1"}) == "R1"

    def test_device_letter_prefixed_by_kicad(self):
        assert element_ref("MQ2", {"Q2"}) == "Q2"
        assert element_ref("XU1", {"U1"}) == "U1"

    def test_case_insensitive(self):
        assert element_ref("r1", {"R1"}) == "R1"

    def test_unknown_reference(self):
        assert element_ref("Rmix", {"R1"}) is None


class TestParse:
    def test_model_cards(self):
        assert _parsed().models == {"__D1": ".model __D1 D"}

    def test_directives_kept_in_order(self):
        assert _parsed().directives == [
            ".options reltol=1e-4",
            ".temp 50",
            ".ic V(/out)=2 V(/far)=1 V(GND)=0",
            ".ic I(L1)=1m",
        ]

    def test_analysis_and_output_directives_dropped(self):
        directives = " ".join(_parsed().directives)

        assert ".tran" not in directives
        assert ".probe" not in directives

    def test_control_block_skipped(self):
        """ngspice commands in .control ... .endc are no circuit lines."""
        names = [e["name"] for e in _parsed().elements]

        assert "set" not in names
        assert "run" not in names

    def test_couplings_kept_apart_from_elements(self):
        sp = _parsed()

        assert [tokens[0] for tokens in sp.couplings] == ["K1", "K2", "K3"]
        assert not any(e["name"].startswith("K") for e in sp.elements)

    def test_include_lines(self):
        sp = _parsed('.title t\n.include "C:/lib/diode.mod"\nD1 a 0 1N4148\n.end')

        assert sp.includes == ['.include "C:/lib/diode.mod"']

    def test_empty_export(self):
        sp = _parsed("")

        assert sp.elements == []
        assert sp.models == {}


class TestSimulatableRefs:
    def test_passives_and_parts_with_model(self):
        refs = _parsed().simulatable_refs(SCHEMATIC_REFS)

        assert refs == {"V1", "R1", "L1", "L2", "R2", "D1", "R9"}

    def test_part_without_model_card(self):
        sp = _parsed(".title t\nQ1 c b e NOMODEL\nR1 a b 1k\n.end")

        assert sp.simulatable_refs(["Q1", "R1"]) == {"R1"}


class TestFilterBlock:
    def _filtered(self):
        return _parsed().filter_block(BLOCK, "GND", SCHEMATIC_REFS)

    def test_only_block_elements(self):
        names = [e["name"] for e in self._filtered()["elements"]]

        assert names == ["V1", "R1", "L1", "L2", "R2", "D1"]

    def test_only_used_models(self):
        assert self._filtered()["models"] == [".model __D1 D"]

    def test_global_directives_taken_over(self):
        directives = self._filtered()["directives"]

        assert ".options reltol=1e-4" in directives
        assert ".temp 50" in directives

    def test_initial_conditions_only_for_block_nodes(self):
        """/far is outside the block, the reference net GND is 0 anyway."""
        directives = self._filtered()["directives"]

        assert ".ic V(/out)=2" in directives
        assert not any("/far" in d or "GND" in d for d in directives)

    def test_coupling_with_both_inductors_in_block(self):
        assert "K1 L1 L2 0.98" in self._filtered()["directives"]

    def test_coupling_with_one_inductor_outside_reported(self):
        filtered = self._filtered()

        assert not any(d.startswith("K2") for d in filtered["directives"])
        assert any("coupling K2" in w and "L9 is not in the block" in w
                   for w in filtered["warnings"])

    def test_coupling_entirely_outside_dropped_silently(self):
        filtered = self._filtered()

        assert not any(d.startswith("K3") for d in filtered["directives"])
        assert not any("K3" in w for w in filtered["warnings"])

    def test_node_directive_outside_and_unknown_format_reported(self):
        warnings = self._filtered()["warnings"]

        assert any(".ic for /far" in w for w in warnings)
        assert any("I(L1)=1m" in w and "format not recognised" in w for w in warnings)

    def test_text_element_touching_block_reported(self):
        """Rmix comes from a schematic text, not from a symbol."""
        warnings = self._filtered()["warnings"]

        assert any("'Rmix /out GND 200'" in w and "connected to /out" in w for w in warnings)

    def test_warnings_ask_to_consider_result(self):
        assert all("take this into account when reading a successful result" in w for w in self._filtered()["warnings"])

    def test_text_element_only_at_reference_not_reported(self):
        sp = _parsed(".title t\nRg /other GND 1k\nV1 /in GND DC 1\nR1 /in GND 1k\n.end")

        filtered = sp.filter_block(["V1", "R1"], "GND", ["V1", "R1"])

        assert filtered["warnings"] == []


class TestBuildIsolatedDeck:
    def test_reference_node_becomes_ground(self):
        deck = build_isolated_deck([_element("Q1 c b GND QMOD"), _element("R1 c GND 1k")],
                                   "GND", {}, [], ".op")

        assert "Q1 c b 0 QMOD" in deck
        assert "R1 c 0 1k" in deck

    def test_supplies_ports_and_loads(self):
        deck = build_isolated_deck([_element("R1 in out 1k")], "GND", {"+5V": "DC 5"},
                                   [("in", "input", "DC 1 AC 1", "R"),
                                    ("out", "load", "10k", "R"),
                                    ("x", "output", "", "R")], ".op")
        lines = deck.splitlines()

        assert "V1_supply +5V 0 DC 5" in lines
        assert "Vin0 in 0 DC 1 AC 1" in lines
        assert "Rload1 out 0 10k" in lines
        assert not any(l.startswith(("Vin2", "Rload2")) for l in lines)

    def test_passive_value_field_cleaned(self):
        deck = build_isolated_deck([_element("R1 a 0 10k/1%"), _element("C1 a 0 1n 50V C0G ic=0")],
                                   "GND", {}, [], ".op")

        assert "R1 a 0 10k" in deck
        assert "C1 a 0 1n ic=0" in deck

    def test_parameter_expression_kept(self):
        deck = build_isolated_deck([_element("R1 a 0 {rv/2}")], "GND", {}, [], ".op")

        assert "R1 a 0 {rv/2}" in deck

    def test_line_order(self):
        deck = build_isolated_deck([_element("R1 a 0 1k")], "GND", {}, [], ".tran 1u 1m",
                                   models=[".model __D1 D"], includes=['.include "x.lib"'],
                                   directives=[".temp 50"], title=".title block")
        lines = deck.splitlines()

        assert lines[:5] == [".title block", ".options savecurrents", '.include "x.lib"',
                             ".temp 50", ".model __D1 D"]
        assert lines[-2:] == [".tran 1u 1m", ".end"]


class TestValidateDeck:
    def test_valid_divider(self):
        result = validate_deck(_deck("V1 in 0 DC 5", "R1 in out 1k", "R2 out 0 1k", ".op"))

        assert result == {"errors": [], "warnings": []}

    def test_no_source(self):
        errors = validate_deck(_deck("R1 a 0 1k", ".op"))["errors"]

        assert any("No source" in e for e in errors)

    def test_no_analysis(self):
        errors = validate_deck(_deck("V1 a 0 DC 1", "R1 a 0 1k"))["errors"]

        assert any("No analysis" in e for e in errors)

    def test_unsupported_analysis(self):
        errors = validate_deck(_deck("V1 a 0 DC 1", "R1 a 0 1k", ".dc V1 0 5 1"))["errors"]

        assert any("'.dc' is not supported" in e for e in errors)

    def test_settings_are_no_analysis(self):
        """.temp / .options / .ic in front of the analysis must not be read as the analysis."""
        result = validate_deck(_deck(".temp 85", ".options reltol=1e-4", ".ic V(a)=1",
                                     "V1 a 0 DC 1", "R1 a 0 1k", ".op"))

        assert result["errors"] == []

    def test_ac_parameters_checked(self):
        errors = validate_deck(_deck("V1 a 0 AC 1", "R1 a 0 1k", ".ac dec 20 1"))["errors"]

        assert any(".ac needs 'dec|oct|lin" in e for e in errors)

    def test_ac_needs_ac_source(self):
        errors = validate_deck(_deck("V1 a 0 DC 1", "R1 a 0 1k", ".ac dec 20 1 1Meg"))["errors"]

        assert any(".ac needs an AC source" in e for e in errors)

    def test_node_named_ac_is_no_ac_source(self):
        errors = validate_deck(_deck("V1 /AC 0 DC 1", "R1 /AC 0 1k", ".ac dec 20 1 1Meg"))["errors"]

        assert any(".ac needs an AC source" in e for e in errors)

    def test_tran_parameters_checked(self):
        errors = validate_deck(_deck("V1 a 0 DC 1", "R1 a 0 1k", ".tran 1u"))["errors"]

        assert any(".tran needs" in e for e in errors)

    def test_passive_without_value(self):
        errors = validate_deck(_deck("V1 a 0 DC 1", "R1 a 0", ".op"))["errors"]

        assert "R1: no value (part DNP/NC?)." in errors

    def test_passive_value_no_number(self):
        errors = validate_deck(_deck("V1 a 0 DC 1", "L2 a 0 FB_bead", ".op"))["errors"]

        assert "L2: value 'FB_bead' is not a SPICE number." in errors

    def test_parameter_expression_accepted(self):
        result = validate_deck(_deck(".param rv=2k", "V1 a 0 DC 1", "R1 a 0 {rv}", ".op"))

        assert result["errors"] == []

    @pytest.mark.parametrize("value", ["1F", "0.47F", "2.2e-3F"])
    def test_farad_without_prefix_warned(self, value):
        warnings = validate_deck(_deck("V1 a 0 DC 1", "R1 a b 1k", f"C1 b 0 {value}", ".op"))["warnings"]
        number = value[:-1]

        assert f"C1: '{value}' means {number} femtofarad in SPICE. For {number} farad write '{number}'." in warnings

    @pytest.mark.parametrize("value", ["100nF", "10uF", "1f", "1"])
    def test_other_capacitances_quiet(self, value):
        warnings = validate_deck(_deck("V1 a 0 DC 1", "R1 a b 1k", f"C1 b 0 {value}", ".op"))["warnings"]

        assert not any("femtofarad" in w for w in warnings)

    def test_source_shorted(self):
        """ngspice treats a node named gnd as ground."""
        errors = validate_deck(_deck("V1 GND 0 DC 1", "R1 a 0 1k", ".op"))["errors"]

        assert any("V1: both terminals on the same node" in e for e in errors)

    def test_parallel_sources(self):
        errors = validate_deck(_deck("V1 a 0 DC 1", "V2 a 0 DC 2", "R1 a 0 1k", ".op"))["errors"]

        assert any("V2 and V1 are in parallel" in e for e in errors)

    def test_node_without_dc_path(self):
        errors = validate_deck(_deck("V1 a 0 DC 1", "R1 a b 1k", "C1 b c 1n", "C2 c 0 1n", ".op"))["errors"]

        assert any("No DC path to ground: c" in e for e in errors)

    def test_coupling_is_no_floating_node(self):
        """K names inductors, not nodes: no 'No DC path: L1, L2'."""
        result = validate_deck(_deck("V1 a 0 DC 1", "L1 a 0 1m", "L2 b 0 1m", "R1 b 0 1k",
                                     "K1 L1 L2 0.9", ".op"))

        assert result["errors"] == []


class TestBuildNetNodeMap:
    def test_renamed_net_mapped_over_passive(self):
        nets = {"Net-(D1-A)": [{"component": "R1", "pin": "1"}, {"component": "D1", "pin": "2"}],
                "/out": [{"component": "R1", "pin": "2"}]}
        elements = [_element("R1 Net-_D1-A_ /out 1k"), _element("D1 /x Net-_D1-A_ DMOD")]

        assert build_net_node_map(nets, elements) == {"Net-(D1-A)": "Net-_D1-A_", "/out": "/out"}

    def test_net_without_passive_not_mapped(self):
        nets = {"Net-(D1-K)": [{"component": "D1", "pin": "1"}]}

        assert build_net_node_map(nets, [_element("D1 Net-_D1-K_ 0 DMOD")]) == {}
