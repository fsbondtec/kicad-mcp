from dataclasses import dataclass
import math
from typing import Tuple, Union, List, Optional, Dict
from collections import defaultdict, deque
import sys

from kiutils.schematic import Schematic
from kiutils.items.schitems import Connection

from kicad_mcp.utils.file_utils import get_project_files

Node = Tuple[float, float] # - Junction: (x, y)
PinNode = Tuple[str, str] # - Pin: (comp_ref, pin_num)
LabelNode = str
NodeType = Union[Node, PinNode, LabelNode]

LABEL_PREFIX = "label:"

@dataclass
class WireSegment:
    """Edge: Wire-Segment"""
    start: NodeType
    end: NodeType
    id: str
    sheet: str = ""


    #return the other end of the wire  
    def get_other_end(self, node: NodeType, tol: float = 0.01) -> Optional[NodeType]:
        if self.nodes_equal(self.start, node):
            return self.end
        elif self.nodes_equal(self.end, node):
            return self.start
        return None
    
    @staticmethod
    def nodes_equal(n1: NodeType, n2: NodeType, tol: float = 0.01) -> bool:
        # label nodes:
        if isinstance(n1, str) and isinstance(n2, str):
            return n1 == n2
        
        #when comparing component pins only reference and pin number are important no coordiantes needed 
        if (isinstance(n1, tuple) and len(n1) == 2 and isinstance(n1[0], str) and
            isinstance(n2, tuple) and len(n2) == 2 and isinstance(n2[0], str)):
            return n1[0] == n2[0] and n1[1] == n2[1]
        
        if (isinstance(n1, tuple) and len(n1) == 2 and 
            isinstance(n1[0], (int, float)) and isinstance(n2[0], (int, float))):
            return abs(n1[0] - n2[0]) < tol and abs(n1[1] - n2[1]) < tol
        
        return False
    

#Graph for all the geometric connections
class GlobalWireGraph:
    def __init__(self, tolerance: float = 0.01):
        self.segments = []  # all edges(Wire + Bridges)
        self.adjacency = defaultdict(list)  # position -> [edges], node -> Wire Segment
        self.component_pins = {}  # comp_ref -> {pin_num: (x, y)}
        self.tolerance = tolerance

        # sheet_path → {label_name → list of positions on that sheet} 
        def make_label_dict():
            return defaultdict(list)

        self._label_positions = defaultdict(make_label_dict)
    
    def _add_wire(self, start: NodeType, end: NodeType,
                  wire_id: str, sheet: str = ""):
        seg = WireSegment(start=start, end=end, id=wire_id, sheet=sheet)
        self.segments.append(seg)
        self.adjacency[start].append(seg)
        self.adjacency[end].append(seg)
        

    def add_wire(self, start: NodeType, end: NodeType, wire_id: str, sheet: str = ""):
        self._add_wire(start, end, wire_id, sheet)


    def add_component_pins(self, comp_ref: str, pins: Dict[str, Tuple[float, float]]):
        """match pins with component"""
        self.component_pins[comp_ref] = pins

    def find_wire_path_between_components(self, comp_a: str, comp_b: str, allowed_components: set = None) -> Optional[List]:
        """BFS von allen Pins von comp_a bis irgendeinen Pin von comp_b"""
        
        if comp_a not in self.component_pins or comp_b not in self.component_pins:
            return None
        
        target_pins = {(comp_b, pin) for pin in self.component_pins[comp_b]}
        
        queue = deque()
        visited = set()
        
        for pin_num in self.component_pins[comp_a]:
            start = (comp_a, pin_num)
            queue.append((start, []))
            visited.add(start)
        
        while queue:
            current, path = queue.popleft()
            
            if current in target_pins:
                return path
            
            for segment in self.adjacency.get(current, []):
                next_node = segment.get_other_end(current)
                if next_node and next_node not in visited:
                    visited.add(next_node)
                    queue.append((next_node, path + [segment]))
            
            if isinstance(current, tuple) and isinstance(current[0], str):
                comp_ref, pin_num = current

                 # only Hop when component in logic Path
                if allowed_components is not None and comp_ref not in allowed_components:
                    continue
                
                if comp_ref in self.component_pins:
                    for other_pin in self.component_pins[comp_ref]:
                        if other_pin != pin_num:
                            other_node = (comp_ref, other_pin)
                            if other_node not in visited and other_node in self.adjacency:
                                visited.add(other_node)
                                hop = {'type': 'component_hop', 'component': comp_ref,
                                    'from_pin': pin_num, 'to_pin': other_pin}
                                queue.append((other_node, path + [hop]))
        
        return None

    def is_pin_node(self, node: NodeType) -> bool:
        """check if node is pin node"""
        return (isinstance(node, tuple) and len(node) == 2 and isinstance(node[0], str))

    def nodes_equal(self, n1: NodeType, n2: NodeType) -> bool:
        """compare nodes"""
        return WireSegment.nodes_equal(n1, n2, self.tolerance)
    
    def build_from_project(self, project_path: str):
        files = get_project_files(project_path)
        
        if "schematic" not in files:
            return set()
        
        schematic_paths = files["schematic"]
        if isinstance(schematic_paths, str):
            schematic_paths = [schematic_paths]
        
        wire_id = 0
        
        for sch_path in schematic_paths:
            try:
                sch = Schematic.from_file(sch_path)

                wire_id = self.parse_sheet(sch, sch_path, wire_id)
                                            
            except Exception as e:
                print(f"Error parsing {sch_path}: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()

        self.connect_hierarchical_labels()

    def parse_sheet(self, sch: Schematic, sch_path: str, wire_id: int) -> int:
        # component pins:
        self.parse_component_pins_for_wire_graph(sch)

        # wires:
        for item in sch.graphicalItems:
            if isinstance(item, Connection):

                points = item.points

                if len(points) < 2:
                    continue

                for i in range(len(points) - 1):
                    start_pos = (points[i].X, points[i].Y)
                    end_pos = (points[i + 1].X, points[i + 1].Y)
            
                    # find nodes on this positions
                    start_node = self.find_node_at_position(start_pos)
                    end_node = self.find_node_at_position(end_pos)
                    
                    self.add_wire(
                        start=start_node,
                        end=end_node,
                        wire_id=f"wire_{wire_id}",
                        sheet = sch_path
                    )
            
                    wire_id += 1

        self.collect_labels(sch, sch_path)
        
        return wire_id

    def collect_labels(self, sch: Schematic, sch_path: str):
       
        for item in sch.globalLabels:
            name = item.text.strip()
            pos  = (item.position.X, item.position.Y)
            self._label_positions[sch_path][f"global:{name}"].append(pos)

        for item in sch.hierarchicalLabels:
            name = item.text.strip()
            pos  = (item.position.X, item.position.Y)
            self._label_positions[sch_path][f"hier:{name}"].append(pos)

        for item in sch.labels:
            name = item.text.strip()
            pos  = (item.position.X, item.position.Y)
            self._label_positions[sch_path][f"local:{sch_path}:{name}"].append(pos)

        # Sheet-Pins 
        for sheet_inst in sch.sheets:
            for pin in sheet_inst.pins:           
                name = pin.name.strip()
                pos  = (pin.position.X, pin.position.Y)
                self._label_positions[sch_path][f"hier:{name}"].append(pos)

    def connect_hierarchical_labels(self):
        hier_label_positions: Dict[str, List[Tuple[float, float]]] = defaultdict(list)

        for sch_path, label_dict in self._label_positions.items():
            for key, positions in label_dict.items():
                if key.startswith("hier:"):
                    hier_label_positions[key].extend(positions)

        for label_key, positions in hier_label_positions.items():
            if len(positions) < 2:
                continue   
            virtual_node = LABEL_PREFIX + label_key
            for pos in positions:
                physical_node = self._resolve_position(pos)
                self._add_wire(physical_node, virtual_node,
                                f"bridge_{label_key}_{pos}", sheet="virtual")

    
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
            self.add_component_pins(comp_ref, pin_positions)

    @staticmethod
    def find_lib_symbol(sch: Schematic, entry_name: str):
        """find library symbol for a entry_name"""
        for lib_sym in sch.libSymbols:
            if lib_sym.entryName == entry_name:
                return lib_sym
        return None
    
    def _resolve_position(self, pos: Tuple[float, float], tolerance: float = 0.1) -> NodeType:
        for comp_ref, pins in self.component_pins.items():
            for pin_num, pin_pos in pins.items():
                dist = ((pin_pos[0] - pos[0])**2 + (pin_pos[1] - pos[1])**2)**0.5
                if dist < tolerance:
                    return (comp_ref, pin_num)
        return pos
                
    def find_node_at_position(self, pos, tolerance: float = 0.1) -> NodeType:
        return self._resolve_position(pos, tolerance)


            
    