import pytest

from kicad_mcp.utils.graph_analysis import CircuitGraph
from kicad_mcp.utils.spice.block import (
    block_warnings,
    classify_block_boundary,
    ground_nets,
    guess_voltage,
    select_block,
    suggest_port_role,
)


def _pin(component, pin, pintype="passive", function=None):
    return {"component": component, "pin": pin, "pinfunction": function, "electrical_type": pintype}


def _graph(tmp_path, nets, power=(), components=None):
    """CircuitGraph from {net: [pins]}; every referenced component gets a plain entry."""
    refs = components or sorted({p["component"] for pins in nets.values() for p in pins})
    netlist_data = {
        "components": {ref: {"lib_id": f"Device:{ref[0]}", "value": "", "name": ref[0]} for ref in refs},
        "nets": nets,
    }
    graph = CircuitGraph(netlist_data, str(tmp_path))
    graph.power_symbols = set(power)
    return graph


def _rc_with_opamp(tmp_path):
    """J1 -> R1 -> C1 -> U1 (no model), C1 and U1 on GND."""
    return _graph(tmp_path, {
        "/in": [_pin("J1", "1", "output"), _pin("R1", "1")],
        "/mid": [_pin("R1", "2"), _pin("C1", "1"), _pin("U1", "3", "input", "+")],
        "GND": [_pin("C1", "2"), _pin("U1", "4", "power_in", "V-")],
    }, power={"GND"})


class TestSelectBlock:
    def test_grows_over_simulatable_parts_only(self, tmp_path):
        block = select_block(_rc_with_opamp(tmp_path), ["R1"], {"R1", "C1"})

        assert block["success"] is True
        assert block["block_components"] == ["C1", "R1"]

    def test_ports_and_global_nets(self, tmp_path):
        block = select_block(_rc_with_opamp(tmp_path), ["R1"], {"R1", "C1"})

        assert [p["net"] for p in block["ports"]] == ["/in", "/mid"]
        assert block["global_nets_touched"] == ["GND"]

    def test_does_not_cross_power_net(self, tmp_path):
        """R2 shares only GND with R1, the block must not grow over it."""
        graph = _graph(tmp_path, {
            "/a": [_pin("R1", "1"), _pin("J1", "1")],
            "GND": [_pin("R1", "2"), _pin("R2", "2")],
            "/b": [_pin("R2", "1"), _pin("J2", "1")],
        }, power={"GND"})

        block = select_block(graph, ["R1"], {"R1", "R2"})

        assert block["block_components"] == ["R1"]
        assert block["global_nets_touched"] == ["GND"]

    def test_lowercase_seed(self, tmp_path):
        block = select_block(_rc_with_opamp(tmp_path), ["r1"], {"R1", "C1"})

        assert block["block_components"] == ["C1", "R1"]

    def test_unknown_seed(self, tmp_path):
        block = select_block(_rc_with_opamp(tmp_path), ["R99"], {"R1", "C1"})

        assert block["success"] is False
        assert "Nicht im Schaltplan gefunden: R99" in block["error"]

    def test_seed_without_model(self, tmp_path):
        block = select_block(_rc_with_opamp(tmp_path), ["U1"], {"R1", "C1"})

        assert block["success"] is False
        assert "Kein Simulationsmodell: U1" in block["error"]

    def test_high_fanout_net_not_followed(self, tmp_path):
        bus = [_pin(f"R{i}", "1") for i in range(1, 13)]
        graph = _graph(tmp_path, {"/bus": bus})
        refs = {f"R{i}" for i in range(1, 13)}

        block = select_block(graph, ["R1"], refs)

        assert block["block_components"] == ["R1"]
        assert block["high_fanout"] == [{"net": "/bus", "fanout": 12}]

    def test_truncated_block_is_the_same_every_time(self, tmp_path):
        """Once max_size is reached the visiting order decides which parts get in;
        it must not depend on Python's per-process set order."""
        graph = _graph(tmp_path, {"/n": [_pin(f"R{i}", "1") for i in range(1, 10)]})
        refs = {f"R{i}" for i in range(1, 10)}

        block = select_block(graph, ["R5"], refs, max_size=4)

        assert block["block_components"] == ["R1", "R2", "R3", "R5"]
        assert block["truncated"] is True


class TestClassifyBlockBoundary:
    def test_dangling_pin(self, tmp_path):
        graph = _graph(tmp_path, {
            "/open": [_pin("R1", "1")],
            "/n": [_pin("R1", "2"), _pin("R2", "1")],
            "/out": [_pin("R2", "2"), _pin("J1", "1")],
        })

        boundary = classify_block_boundary(graph, ["R1", "R2"])

        assert [d["net"] for d in boundary["dangling"]] == ["/open"]
        assert [p["net"] for p in boundary["ports"]] == ["/out"]


class TestSuggestPortRole:
    def test_driver_outside_becomes_input(self):
        port = {"pins_outside": [_pin("U1", "1", "output")]}

        assert suggest_port_role(port) == {"role": "input", "clarify": False}

    def test_only_sinks_outside_becomes_output(self):
        port = {"pins_outside": [_pin("U1", "1", "input"), _pin("U2", "1", "power_in")]}

        assert suggest_port_role(port) == {"role": "output", "clarify": False}

    def test_passive_outside_needs_clarification(self):
        port = {"pins_outside": [_pin("J1", "1", "passive")]}

        assert suggest_port_role(port) == {"role": "output", "clarify": True}


class TestGroundNets:
    def test_gnd_and_zero_first(self):
        assert ground_nets(["AGND", "+5V", "GND", "0"]) == ["GND", "0", "AGND"]

    def test_no_ground(self):
        assert ground_nets(["+5V", "-12V"]) == []


class TestGuessVoltage:
    @pytest.mark.parametrize("net, expected", [
        ("+5V", 5.0),
        ("+3V3", 3.3),
        ("+3.3V", 3.3),
        ("-12V", -12.0),
        ("GND", None),
        ("VCC", None),
    ])
    def test_voltage_from_net_name(self, net, expected):
        assert guess_voltage(net) == expected


class TestBlockWarnings:
    def test_all_pre_checks(self):
        block = {
            "truncated": True,
            "truncation_reason": "max_size=60 reached",
            "high_fanout": [{"net": "/bus", "fanout": 12}],
            "dangling": [{"net": "/open", "pin": _pin("R1", "1")}],
            "export_warning": "Error loading simulation model",
            "global_nets_touched": ["GND", "GND_HV"],
        }

        warnings = block_warnings(block)

        assert any("abgeschnitten (max_size=60 reached)" in w for w in warnings)
        assert any("Netz /bus (12 Anschluesse)" in w for w in warnings)
        assert any("Offener Pin: R1 Pin 1 an Netz /open" in w for w in warnings)
        assert any("KiCad meldete beim SPICE-Export" in w for w in warnings)
        assert any("Mehrere Massenetze (GND, GND_HV)" in w for w in warnings)

    def test_clean_block(self):
        block = {"global_nets_touched": ["GND"], "dangling": [], "high_fanout": []}

        assert block_warnings(block) == []
