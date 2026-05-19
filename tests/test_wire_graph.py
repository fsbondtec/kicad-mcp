import pytest
from kicad_mcp.utils.wire_graph import WireSegment, GlobalWireGraph, LABEL_PREFIX

class TestWireSegmentNodesEqual:
    def test_equal_strings(self):
        assert WireSegment.nodes_equal("label:A", "label:A") is True

    def test_different_strings(self):
        assert WireSegment.nodes_equal("label:A", "label:B") is False

    def test_equal_coordinates(self):
        assert WireSegment.nodes_equal((1.0, 2.0), (1.0, 2.0)) is True

    def test_coordinates_within_tolerance(self):
        assert WireSegment.nodes_equal((1.0, 2.0), (1.005, 2.005), tol=0.01) is True

    def test_coordinates_outside_tolerance(self):
        assert WireSegment.nodes_equal((1.0, 2.0), (1.02, 2.0), tol=0.01) is False

    def test_coordinates_exactly_at_tolerance_boundary(self):
        # distance of exactly tol should NOT match (strict <)
        assert WireSegment.nodes_equal((0.0, 0.0), (0.01, 0.0), tol=0.01) is False

    def test_equal_pin_nodes(self):
        assert WireSegment.nodes_equal(("R1", "1"), ("R1", "1")) is True

    def test_different_pin_number(self):
        assert WireSegment.nodes_equal(("R1", "1"), ("R1", "2")) is False

    def test_different_component_same_pin(self):
        assert WireSegment.nodes_equal(("R1", "1"), ("R2", "1")) is False

    def test_string_vs_coordinate_returns_false(self):
        assert WireSegment.nodes_equal("label", (1.0, 2.0)) is False

    def test_pin_node_vs_coordinate_returns_false(self):
        assert WireSegment.nodes_equal(("R1", "1"), (1.0, 2.0)) is False


class TestWireSegmentGetOtherEnd:
    def test_returns_end_when_queried_from_start(self):
        seg = WireSegment(start=(0.0, 0.0), end=(1.0, 0.0), id="w1")
        assert seg.get_other_end((0.0, 0.0)) == (1.0, 0.0)

    def test_returns_start_when_queried_from_end(self):
        seg = WireSegment(start=(0.0, 0.0), end=(1.0, 0.0), id="w1")
        assert seg.get_other_end((1.0, 0.0)) == (0.0, 0.0)

    def test_unrelated_node_returns_none(self):
        seg = WireSegment(start=(0.0, 0.0), end=(1.0, 0.0), id="w1")
        assert seg.get_other_end((5.0, 5.0)) is None

    def test_pin_node_endpoints(self):
        seg = WireSegment(start=("R1", "1"), end=("R2", "1"), id="w1")
        assert seg.get_other_end(("R1", "1")) == ("R2", "1")
        assert seg.get_other_end(("R2", "1")) == ("R1", "1")

    def test_label_endpoints(self):
        seg = WireSegment(start="label:CLK", end="label:CLK_OUT", id="bridge")
        assert seg.get_other_end("label:CLK") == "label:CLK_OUT"



class TestGlobalWireGraphBasics:
    def test_add_wire_increases_segment_count(self):
        g = GlobalWireGraph()
        g.add_wire((0.0, 0.0), (1.0, 0.0), "w0")
        assert len(g.segments) == 1

    def test_add_wire_registers_both_endpoints_in_adjacency(self):
        g = GlobalWireGraph()
        g.add_wire((0.0, 0.0), (1.0, 0.0), "w0")
        assert len(g.adjacency[(0.0, 0.0)]) == 1
        assert len(g.adjacency[(1.0, 0.0)]) == 1

    def test_add_wire_stores_sheet(self):
        g = GlobalWireGraph()
        g.add_wire((0.0, 0.0), (1.0, 0.0), "w0", sheet="main.sch")
        assert g.segments[0].sheet == "main.sch"

    def test_add_component_pins_stores_correctly(self):
        g = GlobalWireGraph()
        g.add_component_pins("R1", {"1": (0.0, 0.0), "2": (2.54, 0.0)})
        assert "R1" in g.component_pins
        assert g.component_pins["R1"]["1"] == (0.0, 0.0)
        assert g.component_pins["R1"]["2"] == (2.54, 0.0)

    def test_is_pin_node_true(self):
        assert GlobalWireGraph().is_pin_node(("R1", "1")) is True

    def test_is_pin_node_false_for_coordinate(self):
        assert GlobalWireGraph().is_pin_node((1.0, 2.0)) is False

    def test_is_pin_node_false_for_string(self):
        assert GlobalWireGraph().is_pin_node("label:CLK") is False

    def test_nodes_equal_delegates_to_wire_segment(self):
        g = GlobalWireGraph(tolerance=0.05)
        assert g.nodes_equal((0.0, 0.0), (0.04, 0.0)) is True
        assert g.nodes_equal((0.0, 0.0), (0.06, 0.0)) is False


class TestResolvePosition:
    def test_resolves_to_pin_when_within_tolerance(self):
        g = GlobalWireGraph()
        g.add_component_pins("R1", {"1": (10.0, 5.0)})
        assert g._resolve_position((10.0, 5.0)) == ("R1", "1")

    def test_resolves_to_coordinate_when_no_matching_pin(self):
        g = GlobalWireGraph()
        result = g._resolve_position((3.5, 7.2))
        assert result == (3.5, 7.2)

    def test_pin_just_within_tolerance(self):
        g = GlobalWireGraph()
        g.add_component_pins("C1", {"1": (10.0, 5.0)})
        result = g._resolve_position((10.05, 5.05), tolerance=0.1)
        assert result == ("C1", "1")

    def test_pin_outside_tolerance_returns_coordinate(self):
        g = GlobalWireGraph()
        g.add_component_pins("C1", {"1": (10.0, 5.0)})
        result = g._resolve_position((10.5, 5.5), tolerance=0.1)
        assert result != ("C1", "1")

    def test_returns_rounded_coordinate(self):
        g = GlobalWireGraph()
        result = g._resolve_position((1.23456789, 2.98765432))
        # _resolve_position rounds to 3 decimal places
        assert result == (1.235, 2.988)


class TestFindWirePathBetweenComponents:
    def test_missing_component_a_returns_none(self):
        g = GlobalWireGraph()
        g.add_component_pins("R2", {"1": (5.0, 0.0)})
        assert g.find_wire_path_between_components("R1", "R2") is None

    def test_missing_component_b_returns_none(self):
        g = GlobalWireGraph()
        g.add_component_pins("R1", {"1": (0.0, 0.0)})
        assert g.find_wire_path_between_components("R1", "R2") is None

    def test_direct_wire_path(self):
        """R1.pin1 ──wire0── R2.pin1"""
        g = GlobalWireGraph()
        g.add_component_pins("R1", {"1": (0.0, 0.0)})
        g.add_component_pins("R2", {"1": (5.0, 0.0)})
        g.add_wire(("R1", "1"), ("R2", "1"), "w0")

        path = g.find_wire_path_between_components("R1", "R2")
        assert path is not None
        assert len(path) == 1
        assert path[0].id == "w0"

    def test_two_wire_path_via_junction(self):
        """R1.pin1 ──wire0── junction ──wire1── R2.pin1"""
        g = GlobalWireGraph()
        junction = (2.5, 0.0)
        g.add_component_pins("R1", {"1": (0.0, 0.0)})
        g.add_component_pins("R2", {"1": (5.0, 0.0)})
        g.add_wire(("R1", "1"), junction, "w0")
        g.add_wire(junction, ("R2", "1"), "w1")

        path = g.find_wire_path_between_components("R1", "R2")
        assert path is not None
        wire_ids = {s.id for s in path}
        assert "w0" in wire_ids
        assert "w1" in wire_ids

    def test_no_path_returns_none(self):
        g = GlobalWireGraph()
        g.add_component_pins("R1", {"1": (0.0, 0.0)})
        g.add_component_pins("R2", {"1": (5.0, 0.0)})
        # no wires added
        assert g.find_wire_path_between_components("R1", "R2") is None

    def test_component_hop_through_u1(self):
        """R1.pin2 ──w0── U1.pin1  (hop)  U1.pin2 ──w1── R2.pin1"""
        g = GlobalWireGraph()
        g.add_component_pins("R1", {"1": (0.0, 0.0), "2": (2.54, 0.0)})
        g.add_component_pins("U1", {"1": (5.0, 0.0), "2": (7.54, 0.0)})
        g.add_component_pins("R2", {"1": (10.0, 0.0)})
        g.add_wire(("R1", "2"), ("U1", "1"), "w0")
        g.add_wire(("U1", "2"), ("R2", "1"), "w1")

        path = g.find_wire_path_between_components(
            "R1", "R2", allowed_components={"R1", "U1", "R2"}
        )
        assert path is not None
        hop = next((s for s in path if isinstance(s, dict)), None)
        assert hop is not None
        assert hop["component"] == "U1"
        assert hop["type"] == "component_hop"

    def test_allowed_components_blocks_hop(self):
        """Same topology but U1 excluded from allowed set → no path"""
        g = GlobalWireGraph()
        g.add_component_pins("R1", {"1": (0.0, 0.0), "2": (2.54, 0.0)})
        g.add_component_pins("U1", {"1": (5.0, 0.0), "2": (7.54, 0.0)})
        g.add_component_pins("R2", {"1": (10.0, 0.0)})
        g.add_wire(("R1", "2"), ("U1", "1"), "w0")
        g.add_wire(("U1", "2"), ("R2", "1"), "w1")

        path = g.find_wire_path_between_components(
            "R1", "R2", allowed_components={"R1", "R2"}
        )
        assert path is None

    def test_same_component_returns_immediately(self):
        """R1 to R1 — a start pin is already in the target set"""
        g = GlobalWireGraph()
        g.add_component_pins("R1", {"1": (0.0, 0.0), "2": (2.54, 0.0)})
        path = g.find_wire_path_between_components("R1", "R1")
        assert path == []


class TestConnectHierarchicalLabels:
    def test_bridge_created_for_two_matching_labels(self):
        g = GlobalWireGraph()
        g._label_positions["sheet_a.sch"]["hier:CLK"].append((10.0, 5.0))
        g._label_positions["sheet_b.sch"]["hier:CLK"].append((20.0, 5.0))

        g.connect_hierarchical_labels()

        virtual = LABEL_PREFIX + "hier:CLK"
        bridges = [s for s in g.segments if s.start == virtual or s.end == virtual]
        assert len(bridges) == 2

    def test_single_label_occurrence_creates_no_bridge(self):
        g = GlobalWireGraph()
        g._label_positions["sheet_a.sch"]["hier:CLK"].append((10.0, 5.0))
        initial = len(g.segments)

        g.connect_hierarchical_labels()

        assert len(g.segments) == initial

    def test_global_labels_not_bridged(self):
        """global: labels are collected but connect_hierarchical_labels only bridges hier: labels"""
        g = GlobalWireGraph()
        g._label_positions["sheet_a.sch"]["global:VDD"].append((10.0, 5.0))
        g._label_positions["sheet_b.sch"]["global:VDD"].append((20.0, 5.0))
        initial = len(g.segments)

        g.connect_hierarchical_labels()

        assert len(g.segments) == initial

    def test_multiple_label_groups_bridged_independently(self):
        g = GlobalWireGraph()
        g._label_positions["a.sch"]["hier:CLK"].append((0.0, 0.0))
        g._label_positions["b.sch"]["hier:CLK"].append((1.0, 0.0))
        g._label_positions["a.sch"]["hier:DATA"].append((0.0, 1.0))
        g._label_positions["b.sch"]["hier:DATA"].append((1.0, 1.0))

        g.connect_hierarchical_labels()

        clk_virtual = LABEL_PREFIX + "hier:CLK"
        data_virtual = LABEL_PREFIX + "hier:DATA"
        clk_bridges = [s for s in g.segments if clk_virtual in (s.start, s.end)]
        data_bridges = [s for s in g.segments if data_virtual in (s.start, s.end)]
        assert len(clk_bridges) == 2
        assert len(data_bridges) == 2
