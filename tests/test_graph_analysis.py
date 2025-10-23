import unittest
from unittest.mock import patch, mock_open, MagicMock
import tempfile
import os
import pytest

from kicad_mcp.utils.graph_analysis import CircuitGraph, GLOBAL_KICAD_POWER_SYMBOLS

class TestCircuitGraph:


    def test_single_component_no_nets(self):
        """Test graph with single component and no nets"""
        netlist_data = {
            'components': {'C1': {'lib_id': 'Device:C', 'value': 'C', 'footprint': '', 'description': 'Unpolarized capacitor', 'lib': 'Device', 'name': 'C', 'sheet_names': '/'}},
            'nets': {}
        }

        graph = CircuitGraph(netlist_data)
        
        assert 'C1' in graph.nodes
        assert graph.nodes['C1']['type'] == 'component'
        assert graph.nodes['C1']['value'] == 'C'
        assert len(graph.adjacency_list['C1']) == 0

    def test_building_Graph(self):
        """Test building the graph with nets and components
        """

        netlist_data = {
            'components': {
                'C1': {'lib_id': 'Device:C', 'value': 'C', 'footprint': '', 'description': 'Unpolarized capacitor', 'lib': 'Device', 'name': 'C', 'sheet_names': '/'}, 
                'R1': {'lib_id': 'Device:R', 'value': 'R', 'footprint': '', 'description': 'Resistor', 'lib': 'Device', 'name': 'R', 'sheet_names': '/'}}, 
                
                'nets': {
                    'GND': [{'component': 'C1', 'pin': '2'}], 
                    'Net-(C1-Pad1)': [{'component': 'C1', 'pin': '1'}, {'component': 'R1', 'pin': '2'}], 
                    'unconnected-(R1-Pad1)': [{'component': 'R1', 'pin': '1'}]}
        }

        graph = CircuitGraph(netlist_data)


        #Check Nodes
        assert 'C1' in graph.nodes
        assert 'R1' in graph.nodes
        assert 'GND' in graph.nodes
        assert 'Net-(C1-Pad1)' in graph.nodes
        assert 'unconnected-(R1-Pad1)' in graph.nodes

        assert graph.nodes['C1']['type'] == 'component'
        assert graph.nodes['R1']['type'] == 'component'
        assert graph.nodes['GND']['type'] == 'net'
        assert graph.nodes['Net-(C1-Pad1)']['type'] == 'net'

        #Check adjacency
        assert 'Net-(C1-Pad1)' in graph.adjacency_list['R1']
        assert 'Net-(C1-Pad1)' in graph.adjacency_list['C1']
        assert 'GND' in graph.adjacency_list['C1']

        assert 'R1' in graph.adjacency_list['Net-(C1-Pad1)']
        assert 'C1' in graph.adjacency_list['Net-(C1-Pad1)']
        assert 'C1' in graph.adjacency_list['GND']

        #Check Edges
        assert ('R1', 'Net-(C1-Pad1)') in graph.edges
        assert ('C1', 'Net-(C1-Pad1)') in graph.edges
        assert '2' in graph.edges[('R1', 'Net-(C1-Pad1)')]['pins']
        assert '1' in graph.edges[('C1', 'Net-(C1-Pad1)')]['pins']
        assert '2' in graph.edges[('C1', 'GND')]['pins']


    def test_net_with_multiple_Pins(self):
        """Test building the graph with nets and components
        """

        netlist_data = {
            'components': { 
                'R2': {'lib_id': 'Device:R', 'value': 'R', 'footprint': '', 'description': 'Resistor', 'lib': 'Device', 'name': 'R', 'sheet_names': '/'}},
                
                'nets': {
                    'GND': [{'component': 'R2', 'pin': '1'}, {'component': 'R2', 'pin': '2'}, {'component': 'R2', 'pin': '3'}]}
        }

        graph = CircuitGraph(netlist_data)

        edge = graph.edges[('R2', 'GND')]
        assert len(edge['pins']) == 3

    
class TestFindPath:
    """Tests for path finding functionality"""

    #Function to use for Test Data 

    @pytest.fixture
    def simple_chain_netlist(self):
        """R1 --- Net1 --- R2 --- Net2 --- R3"""
        return {
            'components': {
                'R1': {'value': '1k'},
                'R2': {'value': '2k'},
                'R3': {'value': '3k'}
            },
            'nets': {
                'Net1': [
                    {'component': 'R1', 'pin': '2'},
                    {'component': 'R2', 'pin': '1'}
                ],
                'Net2': [
                    {'component': 'R2', 'pin': '2'},
                    {'component': 'R3', 'pin': '1'}
                ]
            }
        }
    
    @pytest.fixture
    def power_net_netlist(self):
        """Circuit with power nets"""
        return {
            'components': {
                'R1': {'lib_id': 'Device:R', 'value': 'R', 'footprint': '', 'description': 'Resistor', 'lib': 'Device', 'name': 'R', 'sheet_names': '/'}, 
                'R2': {'lib_id': 'Device:R', 'value': 'R', 'footprint': '', 'description': 'Resistor', 'lib': 'Device', 'name': 'R', 'sheet_names': '/'}, 
                'U1': {'lib_id': 'Interface_USB:TS3USBCA410', 'value': 'TS3USBCA410', 'footprint': 'Package_DFN_QFN:UQFN-16_1.8x2.6mm_P0.4mm', 'description': 'USB Type-C, SBU 3:1 multiplexer, 500MHz bandwidth, UQFN-16', 'lib': 'Interface_USB', 'name': 'TS3USBCA410', 'sheet_names': '/'}}, 
                
            'nets': {
                'GND': [{'component': 'R2', 'pin': '1'}, {'component': 'U1', 'pin': '4'}], 
                'Net-(R1-Pad2)': [{'component': 'R1', 'pin': '2'}, {'component': 'R2', 'pin': '2'}], 
                'VCC': [{'component': 'R1', 'pin': '1'}, {'component': 'U1', 'pin': '11'}], 
            }
        }
                
    
    def test_path_to_self_component(self, simple_chain_netlist):
        """Test path from component to itself"""

        graph = CircuitGraph(simple_chain_netlist)

        result = graph.find_path('R1', 'R1', ignore_Power=True)
            
        assert result['success'] is True
        assert result['path'] == ['R1']
        assert result['path_length'] == 1
        assert len(result['component_details']) == 1
    
    def test_no_path(self, simple_chain_netlist):
        """Test path with non-existent component"""

        graph = CircuitGraph(simple_chain_netlist)
        result = graph.find_path('R1', 'R20', ignore_Power=False)
        
        assert result is None

    def test_simple_adjacent_path(self, simple_chain_netlist):
        """Test path between adjacent components"""

        graph = CircuitGraph(simple_chain_netlist)
        result = graph.find_path('R1', 'R2', ignore_Power=True)
        
        assert result['success'] is True
        assert 'R1' in result['path']
        assert 'R2' in result['path']
        assert 'Net1' in result['path']
        assert result['path_length'] == 2
        assert len(result['component_details']) == 2
    
    def test_path(self, simple_chain_netlist):
        """Test path between two components"""

        graph = CircuitGraph(simple_chain_netlist)
        result = graph.find_path('R1', 'R3', ignore_Power=True)
        
        assert result['success'] is True

        assert result['path'][0] == 'R1'
        assert result['path'][1] == 'Net1'
        assert result['path'][2] == 'R2'
        assert result['path'][3] == 'Net2'
        assert result['path'][4] == 'R3'

        assert result['path_length'] == 3

    def test_ignore_power_nets_false(self, power_net_netlist):
        """path without power nets"""

        graph = CircuitGraph(power_net_netlist)
        result = graph.find_path('R1', 'U1', ignore_Power=True)
        
        assert result['success'] is False
        assert result['path'] is None
        assert result['path_length'] == 0

    def test_ignore_power_nets_false(self, power_net_netlist):
        """path with power nets"""

        graph = CircuitGraph(power_net_netlist)
        result = graph.find_path('R1', 'U1', ignore_Power=False)
        
        assert result['success'] is True
        assert result['path_length'] == 2  
        assert 'VCC' in result['path']

    def test_power_general(self):

        netlist_data = {
            'components': {
                'R1': {'lib_id': 'Device:R', 'value': 'R', 'footprint': '', 'description': 'Resistor', 'lib': 'Device', 'name': 'R', 'sheet_names': '/'}, 
                'R2': {'lib_id': 'Device:R', 'value': 'R', 'footprint': '', 'description': 'Resistor', 'lib': 'Device', 'name': 'R', 'sheet_names': '/'}, 
                'U1': {'lib_id': 'Interface_USB:TS3USBCA410', 'value': 'TS3USBCA410', 'footprint': 'Package_DFN_QFN:UQFN-16_1.8x2.6mm_P0.4mm', 'description': 'USB Type-C, SBU 3:1 multiplexer, 500MHz bandwidth, UQFN-16', 'lib': 'Interface_USB', 'name': 'TS3USBCA410', 'sheet_names': '/'},
                'C1': {'lib_id': 'Device:R', 'value': 'R', 'footprint': '', 'description': 'Resistor', 'lib': 'Device', 'name': 'R', 'sheet_names': '/'}},
                
            'nets': {
                'GND': [{'component': 'R2', 'pin': '1'}, {'component': 'U1', 'pin': '4'}], 
                'Signal' : [{'component': 'C1', 'pin': '1'}, {'component': 'U1', 'pin': '12'}],
                'Signal1' : [{'component': 'C1', 'pin': '2'}, {'component': 'R1', 'pin': '2'}],
                'VCC': [{'component': 'R1', 'pin': '1'}, {'component': 'U1', 'pin': '11'}], 
            }
        }

        graph = CircuitGraph(netlist_data)

        #shortest Path is through Signal chain when Power Flag is true
        result = graph.find_path('R1', 'U1', ignore_Power=True)

        assert result['success'] is True
        assert result['path_length'] == 3
        assert 'R1' in result['path']
        assert 'C1' in result['path']
        assert 'U1' in result['path'] 

        #shortest Path is through Power when Power Flag is false
        result = graph.find_path('R1', 'U1', ignore_Power=False)
        assert result['success'] is True
        assert result['path_length'] == 2
        assert 'VCC' in result['path']


    def test_max_depth_limit(self, simple_chain_netlist):
        """Test max_depth parameter limits path length"""

        netlist_data = {
            'components': {
                'R1': {'lib_id': 'Device:R', 'value': 'R', 'footprint': '', 'description': 'Resistor', 'lib': 'Device', 'name': 'R', 'sheet_names': '/'}, 
                'R2': {'lib_id': 'Device:R', 'value': 'R', 'footprint': '', 'description': 'Resistor', 'lib': 'Device', 'name': 'R', 'sheet_names': '/'}, 
                'U1': {'lib_id': 'Interface_USB:TS3USBCA410', 'value': 'TS3USBCA410', 'footprint': 'Package_DFN_QFN:UQFN-16_1.8x2.6mm_P0.4mm', 'description': 'USB Type-C, SBU 3:1 multiplexer, 500MHz bandwidth, UQFN-16', 'lib': 'Interface_USB', 'name': 'TS3USBCA410', 'sheet_names': '/'},
                'C1': {'lib_id': 'Device:R', 'value': 'R', 'footprint': '', 'description': 'Resistor', 'lib': 'Device', 'name': 'R', 'sheet_names': '/'}},
                
            'nets': {
                'GND': [{'component': 'R2', 'pin': '1'}, {'component': 'U1', 'pin': '4'}], 
                'Signal' : [{'component': 'C1', 'pin': '1'}, {'component': 'U1', 'pin': '12'}],
                'Signal1' : [{'component': 'C1', 'pin': '2'}, {'component': 'R1', 'pin': '2'}],
                'VCC': [{'component': 'R1', 'pin': '1'}, {'component': 'U1', 'pin': '11'}], 
            }
        }

        graph = CircuitGraph(netlist_data)
        result = graph.find_path('R1', 'U1', ignore_Power=True, max_depth=2)
        
        # Path from R1 to R3 has 3 components, should be limited
        assert result['success'] is True
        assert result['path_length'] == 2
        assert 'R1' in result['path']
        assert 'C1' in result['path']
        assert 'U1' not in result['path']

class TestGetNeighborhood:
    """Tests for neighborhood analysis"""

    

        
        







