import unittest
from unittest.mock import patch, mock_open, MagicMock
import tempfile
import os
import pytest
from kinparse import parse_netlist


from kicad_mcp.utils.net_parser import NetlistParser

class TestNetlistParser(unittest.TestCase):
    """test the functions without external dependencies"""

    def setUp(self):
        """Set up test fixtures"""
        #pytest.set_trace()
        self.test_schematic_path = "/path/to/test.kicad_sch"
        self.parser = NetlistParser(self.test_schematic_path)
        
        # Sample netlist content in KiCad S-expression format
        self.sample_netlist = (r"""(export (version "E")
  (design
    (source "C:\\Users\\messeel\\KiCad\\9.0\\projects\\test_project\\test_project.kicad_sch")
    (date "2025-10-22T09:40:42+0200")
    (tool "Eeschema 9.0.4")
    (sheet (number "1") (name "/") (tstamps "/")
      (title_block
        (title)
        (company)
        (rev)
        (date)
        (source "test_project.kicad_sch")
        (comment (number "1") (value ""))
        (comment (number "2") (value ""))
        (comment (number "3") (value ""))
        (comment (number "4") (value ""))
        (comment (number "5") (value ""))
        (comment (number "6") (value ""))
        (comment (number "7") (value ""))
        (comment (number "8") (value ""))
        (comment (number "9") (value "")))))
  (components
    (comp (ref "C1")
      (value "C")
      (datasheet "~")
      (description "Unpolarized capacitor")
      (fields
        (field (name "Footprint"))
        (field (name "Datasheet") "~")
        (field (name "Description") "Unpolarized capacitor"))
      (libsource (lib "Device") (part "C") (description "Unpolarized capacitor"))
      (property (name "Sheetname") (value "Stammblatt"))
      (property (name "Sheetfile") (value "test_project.kicad_sch"))
      (property (name "ki_keywords") (value "cap capacitor"))
      (property (name "ki_fp_filters") (value "C_*"))
      (sheetpath (names "/") (tstamps "/"))
      (tstamps "beb6ec9b-3943-446d-ab18-4093cbe77e05"))
    (comp (ref "R1")
      (value "15k")
      (datasheet "~")
      (description "Resistor")
      (fields
        (field (name "Footprint"))
        (field (name "Datasheet") "~")
        (field (name "Description") "Resistor"))
      (libsource (lib "Device") (part "R") (description "Resistor"))
      (property (name "Sheetname") (value "Stammblatt"))
      (property (name "Sheetfile") (value "test_project.kicad_sch"))
      (property (name "ki_keywords") (value "R res resistor"))
      (property (name "ki_fp_filters") (value "R_*"))
      (sheetpath (names "/") (tstamps "/"))
      (tstamps "eda499b2-41ed-49ad-a297-d6eb3153db2d")))
  (libparts
    (libpart (lib "Device") (part "C")
      (description "Unpolarized capacitor")
      (docs "~")
      (footprints
        (fp "C_*"))
      (fields
        (field (name "Reference") "C")
        (field (name "Value") "C")
        (field (name "Footprint"))
        (field (name "Datasheet") "~")
        (field (name "Description") "Unpolarized capacitor"))
      (pins
        (pin (num "1") (name "") (type "passive"))
        (pin (num "2") (name "") (type "passive"))))
    (libpart (lib "Device") (part "R")
      (description "Resistor")
      (docs "~")
      (footprints
        (fp "R_*"))
      (fields
        (field (name "Reference") "R")
        (field (name "Value") "R")
        (field (name "Footprint"))
        (field (name "Datasheet") "~")
        (field (name "Description") "Resistor"))
      (pins
        (pin (num "1") (name "") (type "passive"))
        (pin (num "2") (name "") (type "passive")))))
  (libraries
    (library (logical "Device")
      (uri "C:\\Program Files\\KiCad\\9.0\\share\\kicad\\symbols\\/Device.kicad_sym")))
  (nets
    (net (code "1") (name "Net-(C1-Pad2)") (class "Default")
      (node (ref "C1") (pin "2") (pintype "passive"))
      (node (ref "R1") (pin "1") (pintype "passive")))
    (net (code "2") (name "unconnected-(C1-Pad1)") (class "Default")
      (node (ref "C1") (pin "1") (pintype "passive")))
    (net (code "3") (name "unconnected-(R1-Pad2)") (class "Default")
      (node (ref "R1") (pin "2") (pintype "passive")))))""") 
        
    
    def test_init(self):
        """Test initialization of NetlistParser"""
        parser = NetlistParser(self.test_schematic_path)
        self.assertEqual(parser.schematic_path, self.test_schematic_path)
        self.assertEqual(parser.components, {})
        self.assertEqual(parser.nets, {})
        self.assertIsNone(parser.netlist)

    @patch('kicad_mcp.utils.net_parser.find_kicad_cli')
    @patch('subprocess.run')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open)
    #teste den Netlist Export
    def test_export_netlist_successfull(self, mock_file, mock_exists, 
                                    mock_subprocess, mock_find_cli):
        """Test export with MOCKED external dependencies"""
        # Mock external calls
        mock_find_cli.return_value = "C:/Program Files/KiCad/9.0/bin/kicad-cli.exe"
        mock_subprocess.return_value = MagicMock(returncode=0, stderr="")
        mock_exists.return_value = True
        mock_file.return_value.read.return_value = self.sample_netlist
        
        # Test real method with mocked dependencies
        self.parser.export_netlist()
        
        # Verify behavior
        mock_find_cli.assert_called_once()
        mock_subprocess.assert_called_once()
        self.assertEqual(self.parser.netlist, self.sample_netlist)


    @patch("builtins.print")
    @patch('kicad_mcp.utils.net_parser.find_kicad_cli')
    def test_export_netlist_kicad_not_found(self, mock_find_cli, mock_print):
        #Test if exception occurs when no kicad-cli argument
        mock_find_cli.return_value = None
        self.parser.export_netlist()

        #passes when the mock has ever been called with the specific argument
        mock_print.assert_any_call("Error during netlist export: kicad-cli not found. Ensure KiCad 9.0+ is installed and in PATH.")
    

    @patch('kicad_mcp.utils.net_parser.parse_netlist')
    def test_structure_data_components(self, mock_parse):
        #parsing only components 
        #for the parser it has to be in a valid netlist form 

        mock_part1 = MagicMock()
        mock_part1.ref = "R1"
        mock_part1.lib = "Device"
        mock_part1.name = "R"
        mock_part1.value = "15"
        mock_part1.footprint = ""
        mock_part1.desc = "Resistor"
        mock_part1.sheetpath.names = "/"
        
        mock_netlist = MagicMock()
        mock_netlist.parts = [mock_part1]
        mock_netlist.nets = []
        
        mock_parse.return_value = mock_netlist        
        result = self.parser.structure_data()
        
        self.assertIn("R1", result["components"])
        self.assertEqual(result["components"]["R1"]["lib_id"], "Device:R")
        self.assertEqual(result["components"]["R1"]["value"], "15")
        self.assertEqual(result["components"]["R1"]["sheet_names"], "/")

    @patch('kicad_mcp.utils.net_parser.parse_netlist')
    def test_structure_data_nets(self, mock_parse):
        #parsing only nets

        mock_pin1 = MagicMock()
        mock_pin1.ref = "R1"
        mock_pin1.num = "1"
        
        mock_pin2 = MagicMock()
        mock_pin2.ref = "C1"
        mock_pin2.num = "1"
        
        mock_net1 = MagicMock()
        mock_net1.name = "Net-(C1-Pad2)"
        mock_net1.pins = [mock_pin1, mock_pin2]
        
        mock_netlist = MagicMock()
        mock_netlist.parts = []
        mock_netlist.nets = [mock_net1]
        
        mock_parse.return_value = mock_netlist
        result = self.parser.structure_data()

        self.assertIn("Net-(C1-Pad2)", result["nets"])
        self.assertEqual(len(result["nets"]["Net-(C1-Pad2)"]), 2)
        self.assertEqual(result["nets"]["Net-(C1-Pad2)"][0]["component"], "R1")
        self.assertEqual(result["nets"]["Net-(C1-Pad2)"][0]["pin"], "1")
    
    
    @patch('kicad_mcp.utils.net_parser.parse_netlist')
    def test_structure_data_empty_netlist(self, mock_parse):
        #Test with empty netlis

        mock_netlist = MagicMock()
        mock_netlist.parts = []
        mock_netlist.nets = []
        
        mock_parse.return_value = mock_netlist
        self.parser.netlist = ""
        
        result = self.parser.structure_data()
        
        self.assertEqual(result["components"], {})
        self.assertEqual(result["nets"], {})

  
    #Unit / Integration test because Kinparse is used  
    @patch('kicad_mcp.utils.net_parser.find_kicad_cli')
    @patch('subprocess.run')
    def test_workflow_mock(self, mock_subprocess, mock_find_cli):

        mock_find_cli.return_value = "/usr/bin/kicad-cli"

        #checks if subprocess was called 
        mock_subprocess.return_value = MagicMock(returncode=0, stderr="")
        
        sample_netlist = (r"""(export (version "E")
  (design
    (source "C:\\Users\\messeel\\KiCad\\9.0\\projects\\test_project\\test_project.kicad_sch")
    (date "2025-10-22T10:51:09+0200")
    (tool "Eeschema 9.0.4")
    (sheet (number "1") (name "/") (tstamps "/")
      (title_block
        (title)
        (company)
        (rev)
        (date)
        (source "test_project.kicad_sch")
        (comment (number "1") (value ""))
        (comment (number "2") (value ""))
        (comment (number "3") (value ""))
        (comment (number "4") (value ""))
        (comment (number "5") (value ""))
        (comment (number "6") (value ""))
        (comment (number "7") (value ""))
        (comment (number "8") (value ""))
        (comment (number "9") (value "")))))
  (components
    (comp (ref "C1")
      (value "C")
      (datasheet "~")
      (description "Unpolarized capacitor")
      (fields
        (field (name "Footprint"))
        (field (name "Datasheet") "~")
        (field (name "Description") "Unpolarized capacitor"))
      (libsource (lib "Device") (part "C") (description "Unpolarized capacitor"))
      (property (name "Sheetname") (value "Stammblatt"))
      (property (name "Sheetfile") (value "test_project.kicad_sch"))
      (property (name "ki_keywords") (value "cap capacitor"))
      (property (name "ki_fp_filters") (value "C_*"))
      (sheetpath (names "/") (tstamps "/"))
      (tstamps "95fbc6af-3648-4130-bfca-ae6f350b6a54")))
  (libparts
    (libpart (lib "Device") (part "C")
      (description "Unpolarized capacitor")
      (docs "~")
      (footprints
        (fp "C_*"))
      (fields
        (field (name "Reference") "C")
        (field (name "Value") "C")
        (field (name "Footprint"))
        (field (name "Datasheet") "~")
        (field (name "Description") "Unpolarized capacitor"))
      (pins
        (pin (num "1") (name "") (type "passive"))
        (pin (num "2") (name "") (type "passive")))))
  (libraries
    (library (logical "Device")
      (uri "C:\\Program Files\\KiCad\\9.0\\share\\kicad\\symbols\\/Device.kicad_sym")))
  (nets
    (net (code "1") (name "GND") (class "Default")
      (node (ref "C1") (pin "2") (pintype "passive")))
    (net (code "2") (name "unconnected-(C1-Pad1)") (class "Default")
      (node (ref "C1") (pin "1") (pintype "passive")))))""")
        
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=sample_netlist)):
                parser = NetlistParser("/test/path.kicad_sch")
                parser.export_netlist()
                result = parser.structure_data()
                
                self.assertIn("C1", result["components"])
                self.assertIn("GND", result["nets"])
                self.assertEqual(result["components"]["C1"]["value"], "C")

    
        
        



    

