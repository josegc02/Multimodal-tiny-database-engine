from __future__ import annotations

from typing import Any, List, Optional, Tuple

class BplusHeader_file: 
    def __init__(self, M: int, root_pos: int, overflow_state: bool, underflow_state: bool, exception_pos: bool,
                 min_node_pos: int, page_size: int, number_pages: int, is_clustered: bool):
        self.M = M
        self.root_pos = root_pos
        self.overflow_state = overflow_state
        self.underflow_state = underflow_state
        self.exception_pos = exception_pos
        self.min_node_pos = min_node_pos
        self.page_size = page_size
        self.number_pages = number_pages
        self.is_clustered = is_clustered



class BplusNode:
    def __init__(self, fullness:int, childs: List, keys: List, isLeaf: bool, nextLeaf: int):
        self.fullness = fullness
        self.childs = childs
        self.keys = keys
        self.isLeaf = isLeaf
        self.nextLeaf = nextLeaf
        

class BPlusTree:
    def __init__(self, filename: str, root: BplusNode):
        self.filename = filename
        self.root=root
        
