import os
import math
from collections import defaultdict, deque
from typing import Any, Dict, List
import subprocess

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
        self.wire_graph = GlobalWireGraph(tolerance=0.01)
        self._build_wire_graph()



    def load_powerSymbols(self):
        """loads Power Symbols once for the whole class"""
        if self.project_path and self.power_symbols is None:
            self.power_symbols = self.get_powerSymbols()
        else:
            self.power_symbols = set()

    def find_path(self, start: str, end: str, ignore_power: bool, max_depth: int = 10) -> List[str]:
        """Find shortest Path between two components

        Returns:
            List of component references forming the path
        """

        if start not in self.adjacency_list or end not in self.adjacency_list:
            return {
                "success": False,
                "path": None,
                "path_length": 0,
                # "component_details": []
                "nets": [],
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

        queue = deque([(start, [start], 0, None)])  # first Node, Path, component_count
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
                    }

                visited.add(neighbor)
                queue.append((neighbor, new_path, new_comp_count, new_prev_comp))

        return {
            "success": False,
            "path": None,
            "path_length": 0,
            # "component_details": []
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
    
    def mark_path(self, nets: list, layer: str) -> Dict[str, Any]:
        """Highlight the given Nets on the Layout in Kicad"""

        result = {
            "success": False,
            "created_items_length": 0,
            "created_items": [],
            "highlighted_nets": [],
            "used_layer": None,
            "errors": [],
        }

        try:
            if not nets:
                result["errors"].append("No nets provided")
                return result

            if not isinstance(nets, list):
                result["errors"].append("Nets must be a list")
                return result

            try:
                kicad = KiCad()
            except Exception as e:
                result["errors"].append(
                    f"Failed to connect to KiCad: {str(e)}, You need to have Kicad Project running and open"
                )
                return result

            try:
                board = kicad.get_board()
                if not board:
                    result["errors"].append("No board is currently open in KiCad")
                    return result
            except Exception as e:
                result["errors"].append(f"Failed to get board: {str(e)}")
                return result

            enabled_layer_names = []
            for l in board.get_enabled_layers():
                enabled_layer_names.append(board_layer.canonical_name(l))

            # choose given layer or Eco1 or user Layer
            if layer is not None:
                if layer in enabled_layer_names:
                    highlight_layer = board_layer.layer_from_canonical_name(layer)
                    result["used_layer"] = layer
                else:
                    result["errors"].append(
                        f"Layer '{layer}' not found. Available: {enabled_layer_names}"
                    )
                    return result
            else:
                default_layer = "Eco1.User"
                if default_layer in enabled_layer_names:
                    highlight_layer = board_layer.layer_from_canonical_name(default_layer)
                    result["used_layer"] = default_layer
                else:
                    user_layers = [l for l in enabled_layer_names if "Eco" in l or "User" in l]
                    if user_layers:
                        highlight_layer = board_layer.layer_from_canonical_name(user_layers[0])
                        result["used_layer"] = user_layers[0]
                    else:
                        result["errors"].append("No user layers available")
                        return result

            created_items = []
            created_items_id = []
            target_nets = nets

            if not target_nets:
                result["errors"].append("No valid net references found")
                return result

            # start the commit
            try:
                commit = board.begin_commit()
            except Exception as e:
                result["errors"].append(f"Failed to begin commit: {str(e)}")
                return result

            try:
                # Iterate through tracks
                tracks = board.get_tracks()
                if not tracks:
                    result["errors"].append("No tracks found on board")
                    board.push_commit(commit, "Highlighted Path - No tracks")
                    return result

                for track in board.get_tracks():
                    try:
                        net = track.net

                        if net and net.name in target_nets:
                            seg = BoardSegment()

                            start = Vector2()
                            start.x = track.start.x
                            start.y = track.start.y
                            seg.start = start

                            end = Vector2()
                            end.x = track.end.x
                            end.y = track.end.y
                            seg.end = end

                            # layer can be chosen
                            seg.layer = highlight_layer

                            # for highlight take double of original width
                            seg.attributes.stroke.width = int(track.width * 2)

                            created_item = board.create_items(seg)

                            if isinstance(created_item, list):
                                created_items.extend(created_item)
                                for item in created_items:
                                    created_items_id.append(item.id)

                            if net.name not in result["highlighted_nets"]:
                                result["highlighted_nets"].append(net.name)

                    except:
                        result["errors"].append(f"Failed to process track: {str(e)}")
                        continue

                if created_items:
                    try:
                        board.add_to_selection(created_items)
                        result["created_items_length"] = len(created_items)
                        result["created_items"] = created_items_id
                    except Exception as e:
                        result["errors"].append(f"Failed to add items to selection: {str(e)}")
                else:
                    result["errors"].append(f"No tracks found for given nets")

                try:
                    board.push_commit(commit, "Highlighted Path")
                    result["success"] = bool(created_items)
                except Exception as e:
                    result["errors"].append(f"Failed to push commit: {str(e)}")
                    return result

            except Exception as e:
                result["errors"].append(f"Error during track processing: {str(e)}")
                try:
                    board.push_commit(commit, "Highlighted Path - Failed")
                except:
                    pass
                return result

        except Exception as e:
            result["errors"].append(f"Unexpected error: {str(e)}")
            return result

        return result

    def get_user_layers(self) -> Dict[str, Any]:
        """ """

        try:
            kicad = KiCad()
            board = kicad.get_board()

            if not board:
                return {"available": [], "preferred_order": [], "error": "No board open in KiCad"}

            enabled_layers = board.get_enabled_layers()
            layer_names = []

            for layer in enabled_layers:
                layer_names.append(board_layer.canonical_name(layer))

            user_layers = []
            for name in layer_names:
                if name.startswith("User") or name.startswith("Eco"):
                    user_layers.append(name)

            # Reihenfolge
            preferred = []
            for pref in ["Eco1.User", "Eco2.User"] + [f"User.{i}" for i in range(1, 10)]:
                if pref in user_layers:
                    preferred.append(pref)

            for layer in user_layers:
                if layer not in preferred:
                    preferred.append(layer)

            return {
                "available": user_layers,
                "preferred_order": preferred,
                "all_layers": layer_names,
            }

        except Exception as e:
            return {
                "available": ["Eco1.User"],
                "preferred_order": ["Eco1.User"],
                "error": f"Could not connect to KiCad: {str(e)}",
            }

    def unmark_path(self, created_items: list) -> Dict[str, Any]:
        result = {"success": False, "deleted_items": 0, "errors": []}

        try:
            kicad = KiCad()
        except Exception as e:
            result["errors"].append(
                f"Failed to connect to KiCad: {str(e)}, You need to have Kicad Project running and open"
            )
            return result

        try:
            board = kicad.get_board()
            if not board:
                result["errors"].append("No board is currently open in KiCad")
                return result
        except Exception as e:
            result["errors"].append(f"Failed to get board: {str(e)}")
            return result

        try:
            commit = board.begin_commit()

            try:
                board.remove_items_by_id(created_items)
                result["deleted_items"] = len(created_items)
            except Exception as e:
                result["errors"].append(f"Failed to delete items")

            board.push_commit(commit, "Removed Highlight Path")
            result["success"] = result["deleted_items"] > 0

        except Exception as e:
            result["errors"].append(f"Failed to clear highlights: {str(e)}")
            return result

        return result

    def get_neighborhood(self, component: str, ignore_Power: bool, radius: int) -> Dict[str, Any]:
        """Find componoents in a given distance (for Functional Block Analysis)"""

        if component not in self.adjacency_list:
            return {
                "success": False,
                "start": component,
                "neighborhood": [],
                # "details": []
            }

        queue = deque([(component, 0)])  # start component and depth 0
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

        details = [{"ref": ref, **self.nodes[ref]} for ref in allNeighbors if ref in self.nodes]

        return {
            "success": True,
            "start": component,
            "radius": radius,
            "neighborhood": allNeighbors,
            # "details": details
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

    def _build_wire_graph(self):
        """Parse Wire segments and component pins from schematics"""
        
        files = get_project_files(self.project_path)
        
        if "schematic" not in files:
            return set()
        
        schematic_paths = files["schematic"]
        if isinstance(schematic_paths, str):
            schematic_paths = [schematic_paths]
    
        wire_id = 0
        
        for sch_path in schematic_paths:
            try:
                sch = Schematic.from_file(sch_path)
                
                # 1. parse component pins
                self.parse_component_pins_for_wire_graph(sch)
                
                # 2. parse wire segments
                for item in sch.graphicalItems:
                    if item.type == "wire":
                        points = item.points

                        if len(points) < 2:
                            continue

                        for i in range(len(points) - 1):
                            start_pos = (points[i].X, points[i].Y)
                            end_pos = (points[i + 1].X, points[i + 1].Y)
                    
                            # find nodes on this positions
                            start_node = self.find_node_at_position(start_pos)
                            end_node = self.find_node_at_position(end_pos)
                            
                            # Füge Wire hinzu
                            self.wire_graph.add_wire(
                                start=start_node,
                                end=end_node,
                                wire_id=f"wire_{wire_id}"
                            )
                    
                            wire_id += 1
                                
            except Exception as e:
                print(f"Error parsing {sch_path}: {e}")
                import traceback
                traceback.print_exc()


    def parse_component_pins_for_wire_graph(self, sch: Schematic):
        """calculate the component pin positions"""
        
        for symbol in sch.schematicSymbols:
            for instance in symbol.instances:
                for path in instance.paths:
                    comp_ref = path.reference
                    
                    
            
            if comp_ref is None:
                continue

            comp_pos = (symbol.position.X, symbol.position.Y)
            angle_deg = symbol.position.angle or 0
            angle_rad = math.radians(angle_deg)
            
            # find library symbol for this symbolS
            lib_symbol = self.find_lib_symbol(sch, symbol.entryName)
            
            if lib_symbol is None:
                continue
            
            pin_positions = {}
            for unit in lib_symbol.units:
                for pin in unit.pins:
                    print(unit)
                    pin_num = pin.number
                    pin_offset = (pin.position.X, pin.position.Y)

                    rotated_x = (
                    pin_offset[0] * math.cos(angle_rad)
                    - pin_offset[1] * math.sin(angle_rad)
                    )

                    rotated_y = (
                        pin_offset[0] * math.sin(angle_rad)
                        + pin_offset[1] * math.cos(angle_rad)
                    )
                    
                    # calculate offset without rotation
                    absolute_pos = (
                        comp_pos[0] + rotated_x,
                        comp_pos[1] + rotated_y
                    )
                    
                    pin_positions[pin_num] = absolute_pos
                
            #add pins to wire graph
            self.wire_graph.add_component_pins(comp_ref, pin_positions)


    def find_lib_symbol(self, sch: Schematic, entry_name: str):
        """find library symbol for a entry_name"""
        for lib_sym in sch.libSymbols:
            if lib_sym.entryName == entry_name:
                return lib_sym
        return None


    def find_node_at_position(self, pos: Tuple[float, float], 
                            tolerance: float = 0.1) -> NodeType:
        """
        find node at given position 
        
        Returns:
            Pin-Node (comp_ref, pin_num) if position is a pin
            Junction-Node (x, y) else
        """
        
        for comp_ref, pins in self.wire_graph.component_pins.items():
            for pin_num, pin_pos in pins.items():
                dist = ((pin_pos[0] - pos[0])**2 + (pin_pos[1] - pos[1])**2)**0.5
                if dist < tolerance:
                    return (comp_ref, pin_num)
        
        # if no pin was found return normal point
        return pos
    
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
                print(f"Found {len(wire_path)} wire segments: {comp_a}.{comp_b}")
            else:
                print(f"No wire path: {comp_a}.{comp_b}")
            
            i += 1
        
        logical_result["wire_segments"] = all_wire_segments
        
        return logical_result


    def get_pin_for_connection(self, component_ref: str, net_name: str) -> Optional[str]:
        """get a pin number that connects the net with component"""
        
        edge_key = (component_ref, net_name)
        
        if edge_key not in self.edges:
            return None
        
        pins = self.edges[edge_key].get("pins", [])
        
        if pins:
            return pins[0]  #return the first pin (find better solution because there can be multiple pins)
        
        return None
    
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
