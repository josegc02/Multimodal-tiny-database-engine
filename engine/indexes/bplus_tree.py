from __future__ import annotations #nolose
import os # I/O
import struct
from engine.storage.record import RID, Schema # ID
from typing import Any, List, Optional, Tuple #tipos

BPLUS_HEADER_FORMAT = ">qq???qqq?"
BPLUS_HEADER_SIZE = struct.calcsize(BPLUS_HEADER_FORMAT)
DEFAULT_BPLUS_PAGE_SIZE = 4096

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
    def __init__(
        self,
        filename: str,
        schema_def,
        key_field: str,
        M: int = 4,
        page_size: int = DEFAULT_BPLUS_PAGE_SIZE,
        is_clustered: bool = True,
    ):
        self.filename = filename
        self.schema = Schema(schema_def)
        self.key_field = key_field
    
        if key_field not in self.schema.fields:
            raise ValueError(f"key_field '{key_field}' no existe en el schema")

        #nuestro estandar de creacion/lectura del archivo
        is_new = not os.path.exists(filename)
        if os.path.dirname(filename):
            os.makedirs(os.path.dirname(filename), exist_ok=True)
        mode = "w+b" if is_new else "r+b"
        
        self._fh = open(filename, mode) #OTRO ATRIBUTO!


        if not is_new: #es decir, si no es nuevo, o sea, si existia, lees el header
            self.header = self._read_header()
        else: #creas el header con valores iniciales 
            self.header = BplusHeader_file(
                M=M,
                root_pos=-1,
                overflow_state=False,
                underflow_state=False,
                exception_pos=False,
                min_node_pos=-1,
                page_size=page_size,
                number_pages=1,
                is_clustered=is_clustered,
            )
            self._write_header()

    def _read_header(self):
        self._fh.seek(0)
        buf = self._fh.read(BPLUS_HEADER_SIZE)
        if len(buf) != BPLUS_HEADER_SIZE:
            raise ValueError("Archivo B+ tree invalido: header incompleto")
        return BplusHeader_file(*struct.unpack(BPLUS_HEADER_FORMAT, buf))

    def _write_header(self):
        self._fh.seek(0)
        self._fh.write(struct.pack(
            BPLUS_HEADER_FORMAT,
            self.header.M,
            self.header.root_pos,
            self.header.overflow_state,
            self.header.underflow_state,
            self.header.exception_pos,
            self.header.min_node_pos,
            self.header.page_size,
            self.header.number_pages,
            self.header.is_clustered,
        ))
        self._fh.flush()

    def insert(key: str):
        pass

        
