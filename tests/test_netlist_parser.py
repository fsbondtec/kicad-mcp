from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_mcp.utils.net_parser import NetlistParser

SAMPLE_NETLIST = Path(__file__).parent / "test_files" / "nets" / "sample_netlist.net"


def _parser(netlist=None):
    """NetlistParser for a dummy schematic with the given netlist text already loaded."""
    parser = NetlistParser("/path/to/test.kicad_sch")
    parser.netlist = netlist
    return parser


class TestNetlistParserInit:
    def test_init(self):
        parser = NetlistParser("/path/to/test.kicad_sch")

        assert parser.schematic_path == "/path/to/test.kicad_sch"
        assert parser.components == {}
        assert parser.nets == {}
        assert parser.netlist is None


class TestExportNetlist:
    @patch("kicad_mcp.utils.net_parser.export_netlist")
    def test_export_successful(self, mock_export):
        mock_export.return_value = ("(export)", None)
        parser = _parser()

        parser.export_netlist()

        mock_export.assert_called_once_with("/path/to/test.kicad_sch", "kicadsexpr")
        assert parser.netlist == "(export)"

    @patch("kicad_mcp.utils.net_parser.export_netlist")
    def test_file_written_despite_error_code_is_kept(self, mock_export):
        """kicad-cli exits with an error (e.g. missing simulation models) but wrote the file."""
        mock_export.return_value = ("(export)", "kicad-cli export (kicadsexpr) failed (code 2)")
        parser = _parser()

        parser.export_netlist()

        assert parser.netlist == "(export)"

    @patch("kicad_mcp.utils.net_parser.export_netlist")
    def test_no_file_raises(self, mock_export):
        mock_export.return_value = (None, "kicad-cli not found.")
        parser = _parser()

        with pytest.raises(RuntimeError, match="kicad-cli not found"):
            parser.export_netlist()

    @patch("kicad_mcp.utils.net_parser.export_netlist")
    def test_empty_file_raises(self, mock_export):
        mock_export.return_value = ("", None)

        with pytest.raises(RuntimeError, match="empty netlist"):
            _parser().export_netlist()


class TestStructureData:
    def test_components(self):
        data = _parser(SAMPLE_NETLIST.read_text()).structure_data()

        assert set(data["components"]) == {"C1", "R1"}
        assert data["components"]["C1"]["lib_id"] == "Device:C"
        assert data["components"]["C1"]["value"] == "C"
        assert data["components"]["C1"]["name"] == "C"
        assert data["components"]["C1"]["description"] == "Unpolarized capacitor"

    def test_nets_with_pins(self):
        data = _parser(SAMPLE_NETLIST.read_text()).structure_data()

        pins = data["nets"]["Net-(C1-Pad2)"]
        assert [(p["component"], p["pin"]) for p in pins] == [("C1", "2"), ("R1", "1")]
        assert pins[0]["electrical_type"] == "passive"

    def test_unconnected_nets_dropped(self):
        data = _parser(SAMPLE_NETLIST.read_text()).structure_data()

        assert list(data["nets"]) == ["Net-(C1-Pad2)"]

    def test_empty_netlist(self):
        data = _parser(None).structure_data()

        assert data == {"components": {}, "nets": {}}
