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