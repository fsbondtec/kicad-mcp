import os
from collections import defaultdict, deque
from typing import Any, Dict, List
from kiutils.schematic import Schematic

from kicad_mcp.utils.file_utils import get_project_files

class CircuitGraph:
    def __init__(self, netlist_data: Dict[str, Any], project_path: str | None):
        """Initialisiere Graph aus KiCad-Netlist-Daten
        
        Args:
            netlist_data: Parsed netlist from our existing parser
        """
        self.project_path = project_path
        self.nodes = {}
        self.edges = {}
        self.adjacency_list = defaultdict(set)
        self.netlist_data = netlist_data
        self.power_symbols = None
        self.load_powerSymbols()

        self._build_graph()

    def load_powerSymbols(self):
        """loads Power Symbols once for the whole class"""
        if self.project_path and self.power_symbols is None:
            self.power_symbols = self.get_powerSymbols()
        else:
            self.power_symbols = set()
    
    def find_path(self, start: str, end: str, ignore_power:bool, max_depth: int = 10) -> List[str]:
        """Find shortest Path between two components
        
        Returns:
            List of component references forming the path
        """  

        if start not in self.adjacency_list or end not in self.adjacency_list:
            return {
                "success": False,
                "path": None,
                "path_length": 0,
                #"component_details": []
            }
    
        if start == end:
            if self.nodes[start]["type"] == "component":
                component_count = 1
            else:
                component_count = 0

            return {
            "success": True,
            "path": [start],
            "path_length": component_count,
            "component_details": [self.nodes[start]] if self.nodes[start]["type"] == "component" else []
            }
            
        queue = deque([(start, [start], 0)]) #first Node, Path, component_count
        visited = {start}
    
        while queue:
            current, path, comp_count = queue.popleft()

            #if path is longer then max_depth then skip path
            if comp_count >= max_depth:
                continue
            
    
            for neighbor in self.adjacency_list[current]:
                if neighbor in visited:
                    continue
                
                #if abstraction level is low ignore everything but signal connections
                if ignore_power:
                    #first check: is net a known kicad Power Symbol
                    if self.nodes[neighbor]["type"] == "net":
                        if neighbor in self.power_symbols:
                            continue
                    
                    #second check: are the components only connected over power pins?
                    if self.is_power_edge(current, neighbor):
                        continue

                
                #calculate new component count
                new_comp_count = comp_count
                if self.nodes[neighbor]["type"] == "component":
                    new_comp_count = new_comp_count + 1


                new_path = path + [neighbor]
                
                if neighbor == end:

                    component_details = [
                    {"ref": node, **self.nodes[node]} 
                    for node in new_path 
                    if self.nodes[node]["type"] == "component"
                    ]

                            
                    return {
                        "success": True,
                        "path": new_path,
                        "path_length": new_comp_count,
                        "component_details": component_details,
                    }

                visited.add(neighbor)
                queue.append((neighbor, new_path, new_comp_count))

        return {
            "success": False,
            "path": None,
            "path_length": 0,
            #"component_details": []
        } #no path


    def get_neighborhood(self, component: str, ignore_Power: bool, radius: int) -> Dict[str, Any]:
        """Find componoents in a given distance (for Functional Block Analysis)"""

        if component not in self.adjacency_list:
             return {
                "success": False,
                "start": component,
                "neighborhood": [],
                #"details": [] 
            }
        
        queue = deque([(component, 0)]) #start component and depth 0
        visited = {component}
        allNeighbors = []
        depthCounter = 0


        while queue:
            currentNode, currentDepth = queue.popleft()

            if currentDepth >= radius:
                continue

            for neighbor in self.adjacency_list[currentNode]:
                if neighbor in visited:
                    continue


                #if abstraction level is low ignore everything but signal connections
                if ignore_Power:
                    if self.nodes[neighbor]["type"] == "net":
                    #first check: is net a known kicad Power Symbol
                        if neighbor in self.power_symbols:
                            continue

                    #second check: are the components only connected over power pins?
                    if self.is_power_edge(currentNode, neighbor):
                        continue

                visited.add(neighbor)

                #the path is only increased if the node is of type component
                if self.nodes[neighbor]["type"] == "component":
                    queue.append((neighbor, currentDepth + 1))
                else:
                    queue.append((neighbor, currentDepth))

                #whenever Node is a component it is added to the neighbors, nets are only added if the ignore_Power flag is false
                if (self.nodes[neighbor]["type"] == "component") or (not ignore_Power and neighbor in self.power_symbols):
                    allNeighbors.append((currentDepth + 1, neighbor))


        details = [
            {"ref": ref, **self.nodes[ref]}
            for ref in allNeighbors
            if ref in self.nodes
        ]

        return {
            "success": True,
            "start": component,
            "radius": radius,
            "neighborhood": allNeighbors,
            #"details": details
        }

    def _build_graph(self):

        for ref, attrs in self.netlist_data['components'].items():
                self.nodes[ref] = {"type": "component", **attrs}
                self.adjacency_list[ref] = set() #initialize 

        for net_name, connections in self.netlist_data['nets'].items():
            self.nodes[net_name] = {"type": "net"}
            self.adjacency_list[net_name] = set() #initialize so that nodes with no edges are also in adjacency List 

            for conn in connections:
                comp_ref = conn['component']
                pin_num = conn['pin']

                self.adjacency_list[comp_ref].add(net_name) #for nets and for components
                self.adjacency_list[net_name].add(comp_ref)

                edge_key = (comp_ref, net_name)
                if edge_key not in self.edges:
                    self.edges[edge_key] = {"pins": []}
                
                self.edges[edge_key]["pins"].append(pin_num)

    def get_pin_electrical_type(self, component_ref: str, pin_num: str, net_name: str) -> str:
        """Get electrical type of a specific pin from netlist data
        
        Args:
            component_ref: Component reference (e.g., "U2")
            pin_num: Pin number (e.g., "7")
            net_name: Net name (e.g., "+12V")
            
        Returns:
            Electrical type string (e.g., "power_out", "input", "passive")
        """
        
        # Get all components that are connected to this net
        net_connections = self.netlist_data['nets'].get(net_name, [])
        
        # Find the specific pin
        for conn in net_connections:
            if conn['component'] == component_ref and conn['pin'] == pin_num:
                return conn.get('electrical_type')
        
        return 'unspecified'
    
    def is_power_edge(self, from_node: str, to_node: str) -> bool:
        """Check if edge uses power_in or power_out pins
        
        Looks up the electrical types from netlist data for pins on this edge.
        """
        #check what is component and what is net so the edge will always be found if it exists
        if self.nodes[from_node]["type"] == "component" and not self.nodes[to_node]["type"] == "component":
            # Component to Net
            component_ref = from_node
            net_name = to_node
        elif not self.nodes[from_node]["type"] == "component" and self.nodes[to_node]["type"] == "component":
            # Net to Component
            component_ref = to_node
            net_name = from_node
        
        #get the pin nums of the edges
        edge_key = (component_ref, net_name)
        edge_data = self.edges.get(edge_key)
        
        if not edge_data:
            return False
                
        #check the electrical type of connection between specified net and component
        for pin_num in edge_data.get("pins", []):
            electrical_type = self.get_pin_electrical_type(component_ref, pin_num, net_name)
            
            #if pin of type "power_in" or "power_out" block the path
            if electrical_type in ["power_in", "power_out"]:
                return True  
        
        return False


    def get_powerSymbols(self):
        """
        Read all power Symbols and their name from the schematic File,
        to identify power paths better for abstraction

        Args:
            project_path: path to the project (.kicad_pro file)
            
        Returns:
            List of power Symbol names
        """

        #get all Files from Project
        files = get_project_files(self.project_path)

        if "schematic" not in files:
            return set()
        
        #when hierarchical sheets more then one schematic File 
        schematic_paths = files["schematic"]

        if isinstance(schematic_paths, str):
            schematic_paths = [schematic_paths]

        power_symbols = set()

        # get symbols from all schematic sheets 
        for sch_path in schematic_paths:
        
            sch = Schematic.from_file(sch_path)
            
            for inst in sch.schematicSymbols:
                # only get Symbols from power Library

                if inst.libId is not None and inst.libId.startswith("power:"):
                    entry = inst.entryName  
                    
                    #get libsymbol with an iterator
                    libsym = next((ls for ls in sch.libSymbols if ls.entryName == entry), None)
                    
                    if libsym is not None:
                        # Parent Value from libSymbol
                        for prop in libsym.properties:
                            if prop.key == "Value":
                                parent_value = prop.value
                        
                        # Child Value from the instance
                        for prop in inst.properties:
                            if prop.key == "Value":
                                child_value = prop.value
                        
                        final_value = child_value if child_value is not None else parent_value
                        
                        if final_value:
                            power_symbols.add(final_value)
        
        return power_symbols
    