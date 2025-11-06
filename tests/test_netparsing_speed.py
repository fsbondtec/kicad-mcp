import unittest
import time
import os
import pytest

from kicad_mcp.utils.net_parser import NetlistParser

class TestNetlistPerformance(unittest.TestCase):
    """Performance test for netlist parsing"""
    
    @classmethod
    def setUpClass(self):
        """Set up test fixtures once for all tests workflow""" 
        self.test_schematic = "tests/test_schematics/schematics/glasgow.kicad_sch"
        
    def test_full_workflow(self):
        if not os.path.exists(self.test_schematic):
            self.skipTest(f"Schematic file not found: {self.test_schematic}")
        
        parser = NetlistParser(self.test_schematic)
        
        #export time
        start_export = time.perf_counter()  #returns float value of time in seconds
        parser.export_netlist()
        export_time = time.perf_counter() - start_export
        
        #parse time
        start_parse = time.perf_counter()
        result = parser.structure_data()
        parse_time = time.perf_counter() - start_parse
        
        total_time = export_time + parse_time
        
        print(f"Export (KiCad CLI): {export_time:.4f}s")
        print(f"Parse (Kinparse):   {parse_time:.4f}s")
        print(f"Total:              {total_time:.4f}s")
        print(f"Components parsed:  {len(result['components'])}")
        print(f"Nets parsed:        {len(result['nets'])}")
        
        self.assertLess(total_time, 4.0)
        self.assertGreater(len(result["components"]), 0, "Should parse components")
    
    