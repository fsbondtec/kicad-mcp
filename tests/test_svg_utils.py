from kicad_mcp.utils.svg_utils import resolve_pcb_nets


class TestResolvePcbNets:
    def test_exact_match_passes_through(self):
        board_net_names = {"GND", "/Stepper/STEPPER_~{A}", "+24V"}

        known, not_found, resolved = resolve_pcb_nets(["GND"], board_net_names)

        assert known == ["GND"]
        assert not_found == []
        assert resolved == {}

    def test_unique_leaf_match_resolves_via_sheet_path(self):
        """Schematic-side net name lacks the sheet-path prefix the PCB has."""
        board_net_names = {"GND", "/Stepper/STEPPER_~{A}", "+24V"}

        known, not_found, resolved = resolve_pcb_nets(["STEPPER_~{A}"], board_net_names)

        assert known == ["/Stepper/STEPPER_~{A}"]
        assert not_found == []
        assert resolved == {"STEPPER_~{A}": "/Stepper/STEPPER_~{A}"}

    def test_ambiguous_leaf_stays_not_found(self):
        """Same leaf label exists under two different sheet instances - must not guess."""
        board_net_names = {"/Stepper1/EN", "/Stepper2/EN", "GND"}

        known, not_found, resolved = resolve_pcb_nets(["EN"], board_net_names)

        assert known == []
        assert not_found == ["EN"]
        assert resolved == {}

    def test_net_with_slash_but_no_leaf_match_stays_not_found(self):
        """Requested name has a hierarchical prefix, but no board net shares its leaf."""
        board_net_names = {"/Stepper/STEPPER_~{A}", "GND"}

        known, not_found, resolved = resolve_pcb_nets(["/OtherSheet/UNRELATED"], board_net_names)

        assert known == []
        assert not_found == ["/OtherSheet/UNRELATED"]
        assert resolved == {}

    def test_flat_net_without_slash_not_found_does_not_crash(self):
        """Global nets (no '/') that genuinely don't exist must fail cleanly, not raise."""
        board_net_names = {"GND", "+24V"}

        known, not_found, resolved = resolve_pcb_nets(["+5V"], board_net_names)

        assert known == []
        assert not_found == ["+5V"]
        assert resolved == {}

    def test_escaped_slash_in_label_is_not_treated_as_hierarchy_separator(self):
        """KiCad escapes a literal '/' inside a pin/label name as '{slash}'; a name
        containing that substring (but no real '/') must be compared as a whole,
        not accidentally split on the fake separator."""
        board_net_names = {"/Stepper/Net-(U1-SEL0{slash}SDA)", "GND"}

        known, not_found, resolved = resolve_pcb_nets(
            ["Net-(U1-SEL0{slash}SDA)"], board_net_names
        )

        assert known == ["/Stepper/Net-(U1-SEL0{slash}SDA)"]
        assert resolved == {"Net-(U1-SEL0{slash}SDA)": "/Stepper/Net-(U1-SEL0{slash}SDA)"}
        assert not_found == []
