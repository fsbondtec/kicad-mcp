from collections import defaultdict, deque
from typing import Any, Dict, List

GLOBAL_KICAD_POWER_SYMBOLS = [
    '+10V', '+12C', '+12L', '+12LF', '+12P', '+12V', '+12VA', '+15V',
    '+1V0', '+1V1', '+1V2', '+1V35', '+1V5', '+1V8', '+24V', '+28V',
    '+2V5', '+2V8', '+3.3V', '+3.3VA', '+3.3VADC', '+3.3VDAC', '+3.3VP',
    '+36V', '+3V0', '+3V3', '+3V8', '+48V', '+4V', '+5C', '+5F', '+5P',
    '+5V', '+5VA', '+5VD', '+5VL', '+5VP', '+6V', '+7.5V', '+8V', '+9V',
    '+9VA', '+BATT', '+VDC', '+VSW', '-10V', '-12V', '-12VA', '-15V',
    '-24V', '-2V5', '-36V', '-3V3', '-48V', '-5V', '-5VA', '-6V', '-8V',
    '-9V', '-9VA', '-BATT', '-VDC', '-VSW', 'AC', 'Earth', 'Earth_Clean',
    'Earth_Protective', 'GND', 'GND1', 'GND2', 'GND3', 'GNDA', 'GNDD',
    'GNDPWR', 'GNDREF', 'GNDS', 'HT', 'LINE', 'NEUT', 'PRI_HI', 'PRI_LO',
    'PRI_MID', 'PWR_FLAG', 'VAA', 'VAC', 'VBUS', 'VCC', 'VCCQ', 'VCOM',
    'VD', 'VDC', 'VDD', 'VDDA', 'VDDF', 'Vdrive', 'VEE', 'VMEM', 'VPP',
    'VS', 'VSS', 'VSSA'
]

class CircuitGraph:
    def __init__(self, netlist_data: Dict[str, Any]):
        """Initialisiere Graph aus KiCad-Netlist-Daten
        
        Args:
            netlist_data: Parsed netlist from our existing parser
        """
        self.nodes = {}
        self.edges = {}
        self.adjacency_list = defaultdict(set)
        self.netlist_data = netlist_data

        self._build_graph()
    
    def find_path(self, start: str, end: str, ignore_Power: bool, max_depth: int = 10) -> List[str]:
        """Find shortest Path between two components
        
        Returns:
            List of component references forming the path
        """

        if start not in self.adjacency_list or end not in self.adjacency_list:
            return None
    
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
            
        
        queue = deque([(start, [start])])
        visited = {start}
        
        while queue:
            current, path = queue.popleft()
            
            for neighbor in self.adjacency_list[current]:
                if neighbor in visited:
                    continue
                
                if ignore_Power and self.nodes[neighbor]["type"] == "net":
                    if neighbor in [p for p in GLOBAL_KICAD_POWER_SYMBOLS]:
                        continue

                new_path = path + [neighbor]
                
                if neighbor == end:

                    component_details = []
                    limited_path = []
                    component_count = 0
                    for node in new_path:
                        limited_path.append(node)

                        if self.nodes[node]["type"] == "component":
                            component_count += 1
                            component_details.append({"ref": node, **self.nodes[node]})


                            if(component_count >= max_depth):
                                return {
                                    "success": True,
                                    "path": limited_path,
                                    "path_length": component_count,
                                    "component_details": component_details
                                }

                    return {
                        "success": True,
                        "path": new_path,
                        "path_length": component_count,
                        "component_details": component_details
                    }
                
                visited.add(neighbor)
                queue.append((neighbor, new_path))

        return {
            "success": False,
            "path": None,
            "path_length": 0,
            "component_details": []
        } #no path


    def get_neighborhood(self, component: str, ingore_Power: bool, radius: int = 2) -> Dict[str, Any]:
        """Find componoents in a given distance (for Functional Block Analysis)"""

        if component not in self.adjacency_list:
             return {
                "success": False,
                "start": component,
                "neighborhood": [],
                "details": []
            }
        
        queue = deque([(component, 0)]) #start component and depth 0
        visited = {component}
        allNeighbors = []

        while queue:
            currentNode, currentDepth = queue.popleft()

            if currentDepth >= radius:
                continue

            for neighbor in self.adjacency_list[currentNode]:
                if neighbor in visited:
                    continue


                if ingore_Power and  self.nodes[neighbor]["type"] == "net":
                    if neighbor in GLOBAL_KICAD_POWER_SYMBOLS:
                        continue

                visited.add(neighbor)

                #the path is only increased if the node is of type component
                if self.nodes[neighbor]["type"] == "component":
                    queue.append((neighbor, currentDepth + 1))
                else:
                    queue.append((neighbor, currentDepth))

                #whenever Node is a component it is added to the neighbors, nets are only added if the ignore_Power flag is false
                if self.nodes[neighbor]["type"] == "component":
                    allNeighbors.append(neighbor)
                elif not ingore_Power and neighbor in GLOBAL_KICAD_POWER_SYMBOLS:
                    allNeighbors.append(neighbor)

                

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
            "details": details
        }

    
    def classify_component_type(self, component_ref: str) -> str:
        """classify Component Type (compatible with existing System)"""
        pass

    def _build_graph(self):

        for ref, attrs in self.netlist_data['components'].items():
                self.nodes[ref] = {"type": "component", **attrs}

        for net_name, connections in self.netlist_data['nets'].items():
            self.nodes[net_name] = {"type": "net"}

            for conn in connections:
                comp_ref = conn['component']
                pin_num = conn['pin']

                self.adjacency_list[comp_ref].add(net_name) #für net und für komponente
                self.adjacency_list[net_name].add(comp_ref)

                edge_key = (comp_ref, net_name)
                if edge_key not in self.edges:
                    self.edges[edge_key] = {"pins": []}
                
                self.edges[edge_key]["pins"].append(pin_num)

