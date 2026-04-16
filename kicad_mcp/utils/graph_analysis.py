from collections import defaultdict, deque
from typing import Any, Dict, List
import sys

# new Kicad API instead of pcbnew:
from kipy import KiCad
from kipy.common_types import Vector2
from kipy.board_types import BoardSegment
from kipy.util import board_layer

from kiutils.schematic import Schematic

from kicad_mcp.utils.wire_graph import *
from kicad_mcp.utils.file_utils import get_project_files



class CircuitGraph:
    def __init__(self, netlist_data: Dict[str, Any], project_path: str):
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

        #for wire graph 
        self._build_wire_graph()

    def _build_wire_graph(self):
        self.wire_graph = GlobalWireGraph(tolerance=0.01)
        self.wire_graph.build_from_project(self.project_path)

    def load_powerSymbols(self):
        """loads Power Symbols once for the whole class"""
        if self.project_path and self.power_symbols is None:
            self.power_symbols = self.get_powerSymbols()
        else:
            self.power_symbols = set()

    def find_path(self, start: str, end: str, ignore_power: bool, max_depth: int = 10) -> List[str]:
        """Find shortest Path between two components
        Args:
            start: the component where the path should start
            end: component where graph should end
            ignore_power: if true the only connections are found that do not contain a power net
            max_depth: max components in path, default is set to 10

        Returns:
            List of component references forming the path
        """

        start = start.upper()
        end = end.upper()

        if start not in self.adjacency_list or end not in self.adjacency_list:
            return {
                "success": False,
                "path": None,
                "path_length": 0,
                "nets": [],
                "error": "Please enter valid components",
            }
        
        if max_depth == 0:
            return {
                "success": False,
                "path": None,
                "path_length": 0,
                "nets": [],
                "error": "Max depth must be positive",
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
                "component_details": [self.nodes[start]]
                if self.nodes[start]["type"] == "component"
                else [],
                "detailed_path": [start]
            }

        queue = deque([(start, [start], 1, None)])  # first Node, Path, component_count (start counts as 1)
        visited = {start}

        while queue:
            current, path, comp_count, previous_comp = queue.popleft()

            # if path is longer then max_depth then skip path
            if comp_count >= max_depth:
                continue

            for neighbor in self.adjacency_list[current]:
                if neighbor in visited:
                    continue

                # if abstraction level is low ignore everything but signal connections
                if ignore_power:
                    # first check: is net a known kicad Power Symbol
                    if self.nodes[neighbor]["type"] == "net":
                        if neighbor in self.power_symbols:
                            continue

                    # second check: are the components only connected over power pins?
                    if self.is_power_edge(current, neighbor):
                        continue

                # calculate new component count
                new_comp_count = comp_count
                if self.nodes[neighbor]["type"] == "component":
                    new_comp_count = new_comp_count + 1

                new_path = path + [neighbor]

                new_prev_comp = neighbor if self.nodes[neighbor]["type"] == "component" else previous_comp


                if neighbor == end:
                    detailed_path = self._build_detailed_path(new_path)

                    component_details = [
                        {"ref": node, **self.nodes[node]}
                        for node in new_path
                        if self.nodes[node]["type"] == "component"
                    ]

                    nets = [
                        {"ref": node, **self.nodes[node]}
                        for node in new_path
                        if self.nodes[node]["type"] == "net"
                    ]

                    return {
                        "success": True,
                        "path": new_path,
                        "detailed_path": detailed_path,
                        "path_length": new_comp_count,
                        "component_details": component_details,
                        "nets": nets,
                        "debug_power_symbols": sorted(self.power_symbols),
                        "debug_project_files": get_project_files(self.project_path),
                    }

                visited.add(neighbor)
                queue.append((neighbor, new_path, new_comp_count, new_prev_comp))

        return {
            "success": False,
            "path": None,
            "path_length": 0,
        }  # no path

    def _build_detailed_path(self, path: List[str]) -> List[str]:
        """Build path with pin information (e.g., R1.1 -> NET1 -> R2.3)
        
        Args:
            path: List of nodes alternating between components and nets
            
        Returns:
            List with component.pin notation where applicable
        """
        detailed = []
        
        for i, node in enumerate(path):
            if self.nodes[node]["type"] == "component":
                if i > 0: 
                    prev_net = path[i - 1]
                    pins = self.get_pins_for_connection(node, prev_net)
                    if pins:
                        detailed.append(f"{node}.{pins[0]}")
                    else:
                        detailed.append(node)
                elif i < len(path) - 1:  
                    next_net = path[i + 1]
                    pins = self.get_pins_for_connection(node, next_net)
                    if pins:
                        detailed.append(f"{node}.{pins[0]}")
                    else:
                        detailed.append(node)
                else:
                    detailed.append(node)
            else:
                detailed.append(node)
        
        return detailed

    def get_pins_for_connection(self, component: str, net: str) -> List[str]:
        """Get pin numbers connecting a component to a net
        
        Args:
            component: Component reference (e.g., "R1")
            net: Net name (e.g., "NET1")
            
        Returns:
            List of pin numbers (e.g., ["1", "2"])
        """
        edge_key = (component, net)
        edge_data = self.edges.get(edge_key)
        
        if edge_data and "pins" in edge_data:
            return edge_data["pins"]
        
        return []
    
    def get_neighborhood(self, component: str, ignore_Power: bool, radius: int) -> Dict[str, Any]:
        """
        Find componoents in a given distance (for Functional Block Analysis)

         Args:
            component (str): find the neighbors for this specified component
            ignore_Power(bool): if true only neighbors are 

        Returns:
            Dict[str, Any]: A dictionary containing the execution results 
        """

        component = component.upper()
        if component not in self.adjacency_list:
            return {
                "success": False,
                "start": component,
                "neighborhood": [],
            }

        queue = deque([(component, 0)])  # start component and depth 0
        visited = {component}
        allNeighbors = []

        while queue:
            currentNode, currentDepth = queue.popleft()

            if currentDepth >= radius:
                continue

            for neighbor in self.adjacency_list[currentNode]:
                if neighbor in visited:
                    continue

                # if abstraction level is low ignore everything but signal connections
                if ignore_Power:
                    if self.nodes[neighbor]["type"] == "net":
                        # first check: is net a known kicad Power Symbol
                        if neighbor in self.power_symbols:
                            continue

                    # second check: are the components only connected over power pins?
                    if self.is_power_edge(currentNode, neighbor):
                        continue

                visited.add(neighbor)

                # the path is only increased if the node is of type component
                if self.nodes[neighbor]["type"] == "component":
                    queue.append((neighbor, currentDepth + 1))
                else:
                    queue.append((neighbor, currentDepth))

                # whenever Node is a component it is added to the neighbors, nets are only added if the ignore_Power flag is false
                if (self.nodes[neighbor]["type"] == "component") or (
                    not ignore_Power and neighbor in self.power_symbols
                ):
                    allNeighbors.append((currentDepth + 1, neighbor))

        return {
            "success": True,
            "start": component,
            "radius": radius,
            "neighborhood": allNeighbors,
        }

    def _build_graph(self):
        for ref, attrs in self.netlist_data["components"].items():
            self.nodes[ref] = {"type": "component", **attrs}
            self.adjacency_list[ref] = set()  # initialize

        for net_name, connections in self.netlist_data["nets"].items():
            self.nodes[net_name] = {"type": "net"}
            self.adjacency_list[net_name] = (
                set()
            )  # initialize so that nodes with no edges are also in adjacency List

            for conn in connections:
                comp_ref = conn["component"]
                pin_num = conn["pin"]

                self.adjacency_list[comp_ref].add(net_name)  # for nets and for components
                self.adjacency_list[net_name].add(comp_ref)

                edge_key = (comp_ref, net_name)
                if edge_key not in self.edges:
                    self.edges[edge_key] = {"pins": []}

                self.edges[edge_key]["pins"].append(pin_num)

    ######################### Methods for Wire Graph #########################

    def find_path_with_wire_segments(self, start: str, end: str, 
                                  ignore_power: bool, 
                                  max_depth: int = 10) -> Dict[str, Any]:
        """
        finds logical Path + wires through that path    

        Returns:
            Dict with :
            - success, path, path_length, component_details, nets
            - wire_segments: list of all wire segments in the path 
        """
        # logic path
        logical_result = self.find_path(start, end, ignore_power, max_depth)
        
        if not logical_result["success"]:
            logical_result["wire_segments"] = []
            return logical_result
        
        # wire path
        path = logical_result["path"]

        allowed = {n for n in path if self.nodes[n]["type"] == "component"}

        all_wire_segments = []
        
        i = 0
        while i < len(path):
            node = path[i]
            
            # net -> get next component
            if self.nodes[node]["type"] != "component":
                i += 1
                continue
            
            comp_a = node
            
            next_comp = None
            net_between = None
            
            for j in range(i + 1, len(path)):
                if self.nodes[path[j]]["type"] == "net":
                    net_between = path[j]
                elif self.nodes[path[j]]["type"] == "component":
                    next_comp = path[j]
                    break
            
            if next_comp is None or net_between is None:
                i += 1
                continue
            
            comp_b = next_comp
            
            wire_path = self.wire_graph.find_wire_path_between_components(comp_a, comp_b, allowed_components=allowed)

                
            if wire_path:
                all_wire_segments.extend(wire_path)
                print(f"Found {len(wire_path)} wire segments: {comp_a}.{comp_b}", file=sys.stderr)
            else:
                print(f"No wire path: {comp_a}.{comp_b}", file=sys.stderr)
            
            i += 1
        
        #format
        formatted_segments = []
        for segment in all_wire_segments:
            if isinstance(segment, dict):
                # Component hop
                comp_ref = segment['component']
                from_pin = segment['from_pin']
                to_pin = segment['to_pin']
                
                pins = self.wire_graph.component_pins.get(comp_ref, {})
                from_pos = pins.get(from_pin)
                to_pos = pins.get(to_pin)
                
                formatted_segments.append({
                    "type": "component_hop",
                    "component": comp_ref,
                    "from_pin": from_pin,
                    "to_pin": to_pin,
                    "from_position": {"x": from_pos[0], "y": from_pos[1]} if from_pos else None,
                    "to_position": {"x": to_pos[0], "y": to_pos[1]} if to_pos else None,
                    "net": segment.get('net')
                })
            else:
                # Wire segment
                formatted_segments.append({
                    "type": "wire",
                    "id": segment.id,
                    "sheet": segment.sheet,
                    "start": self.format_node(segment.start),
                    "end": self.format_node(segment.end)
                })

        logical_result["wire_segments_raw"] = all_wire_segments # Falls du die Rohdaten intern nochmal brauchst
        logical_result["wire_segments_formatted"] = formatted_segments
        
        return logical_result
    
    def format_node(self, node) -> Dict[str, Any]:
        """Format node for output (internal helper)"""
        if isinstance(node, str):
            return {"type": "label", "name": node}
            
        if isinstance(node, tuple):
            if len(node) == 2:
                if isinstance(node[0], str):
                    # Pin node: (comp_ref, pin_num)
                    comp_ref, pin_num = node
                    pos = self.wire_graph.component_pins.get(comp_ref, {}).get(pin_num)
                    return {
                        "type": "pin",
                        "component": comp_ref,
                        "pin": pin_num,
                        "position": {"x": pos[0], "y": pos[1]} if pos else None
                    }
                else:
                    # Junction node: (x, y)
                    return {
                        "type": "junction",
                        "position": {"x": node[0], "y": node[1]}
                    }
        return {"type": "unknown", "value": str(node)}
        ###################################################################


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
        net_connections = self.netlist_data["nets"].get(net_name, [])

        # Find the specific pin
        for conn in net_connections:
            if conn["component"] == component_ref and conn["pin"] == pin_num:
                return conn.get("electrical_type")

        return "unspecified"

    def is_power_edge(self, from_node: str, to_node: str) -> bool:
        """Check if edge uses power_in or power_out pins

        Looks up the electrical types from netlist data for pins on this edge.
        """
        # check what is component and what is net so the edge will always be found if it exists
        if (
            self.nodes[from_node]["type"] == "component"
            and not self.nodes[to_node]["type"] == "component"
        ):
            # Component to Net
            component_ref = from_node
            net_name = to_node
        elif (
            not self.nodes[from_node]["type"] == "component"
            and self.nodes[to_node]["type"] == "component"
        ):
            # Net to Component
            component_ref = to_node
            net_name = from_node

        # get the pin nums of the edges
        edge_key = (component_ref, net_name)
        edge_data = self.edges.get(edge_key)

        if not edge_data:
            return False

        # check the electrical type of connection between specified net and component
        for pin_num in edge_data.get("pins", []):
            electrical_type = self.get_pin_electrical_type(component_ref, pin_num, net_name)

            # if pin of type "power_in" or "power_out" block the path
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

        # get all Files from Project
        files = get_project_files(self.project_path)

        if "schematic" not in files:
            return set()

        # when hierarchical sheets more then one schematic File
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

                    # get libsymbol with an iterator
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

    