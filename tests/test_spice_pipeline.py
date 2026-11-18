import os
import shutil
from pathlib import Path

import pytest

from kicad_mcp.utils.cli_drc import find_kicad_cli
from kicad_mcp.utils.spice.deck import assemble_deck, select_ports
from kicad_mcp.utils.spice.runner import run_deck


def _demo_dir():
    """KiCad's simulation demos next to the kicad-cli that the server uses, or None."""
    cli = find_kicad_cli()
    if not cli:
        return None
    demos = Path(cli).parent.parent / "share" / "kicad" / "demos" / "simulation"
    return demos if demos.is_dir() else None


DEMOS = _demo_dir()

pytestmark = [
    pytest.mark.requires_kicad,
    pytest.mark.slow,
    pytest.mark.skipif(DEMOS is None, reason="KiCad mit Simulations-Demos nicht installiert"),
]


def _demo(tmp_path, name, schematic):
    """Copy a demo into tmp_path (the export must never write into the installation)
    and return (project_path, schematic_path)."""
    target = tmp_path / os.path.basename(name)
    shutil.copytree(DEMOS / name, target)
    sch = target / schematic
    return str(sch.with_suffix(".kicad_pro")), str(sch)


class TestRectifier:
    def test_block_and_ports(self, tmp_path):
        project, sch = _demo(tmp_path, "rectifier", "rectifier.kicad_sch")

        graph, block, ports = select_ports(project, sch, "R1")

        assert block["success"] is True
        assert block["block_components"] == ["C1", "D1", "R1", "R2", "V1"]
        assert block["global_nets_touched"] == ["GND"]
        assert ports == []

    def test_transient_runs(self, tmp_path):
        project, sch = _demo(tmp_path, "rectifier", "rectifier.kicad_sch")

        deck, error, warnings = assemble_deck(project, sch, "R1", [], ".tran 1u 5m", "GND", [])
        result = run_deck(deck)

        assert error is None
        assert result["success"] is True, result["errors"]

        nodes = result["sweep"]["nodes"]
        out, source = nodes["/rect_out"].real, nodes["/signal_in"].real
        assert out.max() > 0.1
        assert out.min() > -0.05                
        assert out.max() < abs(source).max()    


class TestRoyer:
    def _deck(self, tmp_path, seed):
        project, sch = _demo(tmp_path, os.path.join("power_supplies", "royer"), "royer1.kicad_sch")
        return assemble_deck(project, sch, seed, [], ".op", "GND", [{"net": "+12V", "value": "DC 12"}])

    def test_couplings_and_options_taken_over(self, tmp_path):
        deck, error, warnings = self._deck(tmp_path, "L1")
        lines = deck.splitlines()

        assert error is None
        assert {"K1 L1 L2 0.98", "K2 L1 L3 0.98", "K4 L2 L3 0.98"} <= set(lines)
        assert ".options chgtol=1e-11 abstol=1u noinit" in lines

    def test_couplings_to_inductor_outside_reported(self, tmp_path):
        deck, error, warnings = self._deck(tmp_path, "L1")

        coupling_warnings = [w for w in warnings if "Kopplung" in w]
        assert len(coupling_warnings) == 3
        assert all("liegt nicht im Block" in w for w in coupling_warnings)
        assert not any(l.startswith(("K3", "K5", "K6")) for l in deck.splitlines())


class TestSallenKey:
    def test_opamp_vendor_model_runs(self, tmp_path):
        """AD8051 uses POLY sources, which need the XSPICE code models."""
        project, sch = _demo(tmp_path, "sallen_key", "sallen_key.kicad_sch")

        deck, error, warnings = assemble_deck(project, sch, "R1", [], ".ac dec 10 1 1Meg", "GND",
                                              [{"net": "VDD", "value": "DC 10"},
                                               {"net": "VSS", "value": "DC -10"}])
        result = run_deck(deck)

        assert error is None
        assert result["success"] is True, result["errors"]
        assert not any("MIF-ERROR" in e for e in result["errors"])


class TestErrors:
    def test_unknown_seed(self, tmp_path):
        project, sch = _demo(tmp_path, "rectifier", "rectifier.kicad_sch")

        deck, error, warnings = assemble_deck(project, sch, "R99", [], ".op")

        assert deck is None
        assert "Nicht im Schaltplan gefunden: R99" in error
