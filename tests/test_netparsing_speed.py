import unittest
import time
import os
import pytest

from kicad_mcp.utils.net_parser import NetlistParser

test_schematic = "tests/test_files/schematics/glasgow.kicad_sch"

class TestNetlistPerformance(unittest.TestCase):
    """Performance test for netlist parsing"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures once for all tests workflow""" 
        cls.test_schematic = test_schematic
        
    def test_full_workflow(self):
        if not os.path.exists(self.test_schematic):
            self.skipTest(f"Schematic file not found: {self.test_schematic}")
        
        parser = NetlistParser(self.test_schematic)
        
        #export time
        start_export = time.perf_counter()
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
        
        self.assertGreater(len(result["components"]), 0, "Should parse components")
    
@pytest.fixture
def sample_schematic():
    return test_schematic


def test_full_workflow_benchmark(benchmark, sample_schematic):    
    if not os.path.exists(sample_schematic):
        pytest.skip(f"Schematic file not found: {sample_schematic}")
    
    def workflow():
        parser = NetlistParser(sample_schematic)
        parser.export_netlist()
        result = parser.structure_data()
        return result
    
    result = benchmark(workflow)
    
    assert len(result["components"]) > 0, "Should parse components"
    assert len(result["nets"]) > 0, "Should parse nets"
        