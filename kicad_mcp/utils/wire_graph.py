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
        
    
    def find_wire_path(self, comp_a: str, pin_a: str, comp_b: str, pin_b: str) -> Optional[List]:
        """find wire path between two component pins"""
        
        start_node = (comp_a, pin_a)
        end_node = (comp_b, pin_b)
        
        return self.wire_bfs(start_node, end_node)
    
    def wire_bfs(self, start_node: NodeType, end_node: NodeType) -> Optional[List]:
        """BFS"""
        
        queue = deque([(start_node, [])])
        visited = set()
        
        while queue:
            current, path = queue.popleft()
            
            if current in visited:
                continue
            visited.add(current)
            
            #finished
            if self.nodes_equal(current, end_node):
                return path
            
            #follow wire segments through the graph
            for wire_segment in self.adjacency.get(current, []):
                next_node = wire_segment.get_other_end(current, self.tolerance)
                if next_node and next_node not in visited:
                    queue.append((next_node, path + [wire_segment]))

            #pin to pin connection in component
            if self.is_pin_node(current):
                comp_ref, current_pin = current
            
            if comp_ref in self.component_pins:
                    for other_pin in self.component_pins[comp_ref].keys():
                        if other_pin == current_pin:
                            continue
                            
                        other_node = (comp_ref, other_pin)

                        #just look at the other pin if other pin is valid 
                        if other_node in self.adjacency and other_node not in visited:
                            hop = {
                                'type': 'component_hop',
                                'component': comp_ref,
                                'from_pin': current_pin,
                                'to_pin': other_pin
                            }
                            queue.append((other_node, path + [hop]))
        
        return None
    
    def is_pin_node(self, node: NodeType) -> bool:
        """check if node is pin node"""
        return (isinstance(node, tuple) and len(node) == 2 and isinstance(node[0], str))

    def nodes_equal(self, n1: NodeType, n2: NodeType) -> bool:
        """compare nodes"""
        return WireSegment.nodes_equal(n1, n2, self.tolerance)

                
    @staticmethod
    def nodes_equal(n1: NodeType, n2: NodeType, tol=0.01) -> bool:
        # Pin-Knoten
        if len(n1) == 4 and len(n2) == 4:
            return n1[0] == n2[0] and n1[1] == n2[1]
        
        # Junction
        if len(n1) == 2 and len(n2) == 2:
            return abs(n1[0] - n2[0]) < tol and abs(n1[1] - n2[1]) < tol
        
        return False
    