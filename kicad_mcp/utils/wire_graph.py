from dataclasses import dataclass
from typing import Tuple, Union, List, Optional, Dict, Any
from collections import defaultdict, deque

from kiutils.schematic import Schematic

# Knoten kann sein:
Node = Tuple[float, float] # - Junction: (x, y)
PinNode = Tuple[str, str] # - Pin: (comp_ref, pin_num)
NodeType = Union[Node, PinNode]


@dataclass
class WireSegment:
    """Edge: Wire-Segment"""
    start: NodeType
    end: NodeType
    id: str

    #return the other end of the wire  
    def get_other_end(self, node: NodeType, tol: float = 0.01) -> Optional[NodeType]:
        if self.nodes_equal(self.start, node):
            return self.end
        elif self.nodes_equal(self.end, node):
            return self.start
        return None
    
    @staticmethod
    def nodes_equal(n1: NodeType, n2: NodeType, tol: float = 0.01) -> bool:
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
    
    def add_wire(self, start: NodeType, end: NodeType, wire_id: str):
        """add wire segment to Graph"""
        segment = WireSegment(start=start, end=end, id=wire_id)
        self.segments.append(segment)
        self.adjacency[start].append(segment)
        self.adjacency[end].append(segment)

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

            
    