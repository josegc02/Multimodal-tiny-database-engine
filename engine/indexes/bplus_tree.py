from __future__ import annotations #nolose
import os # I/O
import struct
from engine.storage.record import RID, Schema # ID
from typing import Any, List, Optional, Tuple #tipos

BPLUS_HEADER_FORMAT = ">qq??qqqq?"
BPLUS_HEADER_SIZE = struct.calcsize(BPLUS_HEADER_FORMAT)
DEFAULT_BPLUS_PAGE_SIZE = 4096
CHILD_FORMAT = ">q"
CHILD_SIZE = struct.calcsize(CHILD_FORMAT)
NODE_HEADER_FORMAT = ">q?q"
NODE_HEADER_SIZE = struct.calcsize(NODE_HEADER_FORMAT)
EMPTY_CHILD = -1
MAIN_FILE_FLAG = 0
AUX_FILE_FLAG = 1
RID_SLOT_BITS = 31
RID_PAGE_BITS = 31
RID_SLOT_MASK = (1 << RID_SLOT_BITS) - 1
RID_PAGE_MASK = (1 << RID_PAGE_BITS) - 1

class BplusHeader_file: 
    def __init__(self, M: int, root_pos: int, overflow_state: bool, underflow_state: bool, exception_pos: int,
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
    def __init__(self, fullness:int, childs: List, keys: List, isLeaf: bool, nextLeaf: int = EMPTY_CHILD):
        self.fullness = fullness
        self.childs = childs
        self.keys = keys
        self.isLeaf = isLeaf
        self.nextLeaf = nextLeaf
        # en un mismo espacio de memoria se deberia ver:
        # [hijo 0, key 0, hijo 1, key 1, ..., hijo M-1, key M-1, hijo M]
        

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

        self._configure_key_layout()

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
                exception_pos=-1,
                min_node_pos=-1,
                page_size=page_size,
                number_pages=1,
                is_clustered=is_clustered,
            )
            self._write_header()
        self._configure_node_layout()

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

    def _configure_key_layout(self):
        key_index = self.schema.fields.index(self.key_field)
        self.key_type = self.schema.types[key_index]
        self.key_size = self.schema.sizes[key_index]
        if self.key_type == "int":
            self.key_format = "q"
            self._key_struct_format = ">q"
        elif self.key_type == "float":
            self.key_format = "d"
            self._key_struct_format = ">d"
        elif self.key_type == "str":
            self.key_format = f"{self.key_size}s"
            self._key_struct_format = None
        else:
            raise ValueError(f"Tipo de key no soportado: {self.key_type}")

    def _configure_node_layout(self):
        self.node_body_size = (self.header.M * (CHILD_SIZE + self.key_size)) + CHILD_SIZE
        self.node_size = NODE_HEADER_SIZE + self.node_body_size
        if self.node_size > self.header.page_size:
            raise ValueError("El nodo B+ no cabe en una pagina con el M y key_field dados")

    def _page_offset(self, page_id: int) -> int:
        if type(page_id) is not int or page_id < 0:
            raise ValueError("page_id invalido")
        return page_id * self.header.page_size

    def _allocate_node(self) -> int:
        page_id = self.header.number_pages
        self.header.number_pages += 1
        self._write_header()
        self._fh.seek(self._page_offset(page_id))
        self._fh.write(b"\x00" * self.header.page_size)
        self._fh.flush()
        return page_id

    def _serialize_key(self, key: Any) -> bytes:
        if self.key_type == "int":
            return struct.pack(self._key_struct_format, int(key))
        if self.key_type == "float":
            return struct.pack(self._key_struct_format, float(key))
        encoded = str(key).encode("utf-8")[:self.key_size]
        return encoded.ljust(self.key_size, b"\x00")

    def _deserialize_key(self, data: bytes) -> Any:
        if self.key_type == "int":
            return struct.unpack(self._key_struct_format, data)[0]
        if self.key_type == "float":
            return struct.unpack(self._key_struct_format, data)[0]
        return data.rstrip(b"\x00").decode("utf-8")

    def _normalize_key(self, key: Any) -> Any:
        if self.key_type == "int":
            return int(key)
        if self.key_type == "float":
            return float(key)
        return str(key)[:self.key_size]

    def _validate_node_shape(self, node: BplusNode) -> None:
        if not 0 <= node.fullness <= self.header.M:
            raise ValueError("fullness invalido")
        if len(node.keys) > self.header.M:
            raise ValueError("demasiadas keys en el nodo")
        if len(node.childs) > self.header.M + 1:
            raise ValueError("demasiados childs en el nodo")

    def _read_node(self, page_id: int) -> BplusNode:
        self._fh.seek(self._page_offset(page_id))
        header = self._fh.read(NODE_HEADER_SIZE)
        if len(header) != NODE_HEADER_SIZE:
            raise ValueError("Nodo B+ invalido: header incompleto")
        fullness, is_leaf, next_leaf = struct.unpack(NODE_HEADER_FORMAT, header)
        childs = []
        keys = []
        for i in range(self.header.M):
            child_data = self._fh.read(CHILD_SIZE)
            key_data = self._fh.read(self.key_size)
            if len(child_data) != CHILD_SIZE or len(key_data) != self.key_size:
                raise ValueError("Nodo B+ invalido: cuerpo incompleto")
            child = struct.unpack(CHILD_FORMAT, child_data)[0]
            childs.append(child)
            if i < fullness:
                keys.append(self._deserialize_key(key_data))
        last_child_data = self._fh.read(CHILD_SIZE)
        if len(last_child_data) != CHILD_SIZE:
            raise ValueError("Nodo B+ invalido: ultimo child incompleto")
        childs.append(struct.unpack(CHILD_FORMAT, last_child_data)[0])
        return BplusNode(fullness, childs, keys, is_leaf, next_leaf)

    def _write_node(self, page_id: int, node: BplusNode) -> None:
        self._validate_node_shape(node)
        keys = list(node.keys) + [None] * (self.header.M - len(node.keys))
        childs = list(node.childs) + [EMPTY_CHILD] * (self.header.M + 1 - len(node.childs))
        buf = bytearray()
        buf.extend(struct.pack(NODE_HEADER_FORMAT, node.fullness, node.isLeaf, node.nextLeaf))
        for i in range(self.header.M):
            buf.extend(struct.pack(CHILD_FORMAT, int(childs[i])))
            if i < node.fullness:
                buf.extend(self._serialize_key(keys[i]))
            else:
                buf.extend(b"\x00" * self.key_size)
        buf.extend(struct.pack(CHILD_FORMAT, int(childs[self.header.M])))
        buf.extend(b"\x00" * (self.header.page_size - len(buf)))
        self._fh.seek(self._page_offset(page_id))
        self._fh.write(buf)
        self._fh.flush()

    def _pack_leaf_payload(self, payload: Any) -> int:
        if self.header.is_clustered:
            if type(payload) is not int or payload < 0:
                raise ValueError("En indice clustered el payload de hoja debe ser un page_id entero")
            return payload
        if type(payload) is int:
            return payload
        if not isinstance(payload, RID):
            raise TypeError("En indice unclustered el payload de hoja debe ser RID o int empaquetado")
        if payload.file == "main":
            file_flag = MAIN_FILE_FLAG
        elif payload.file == "aux":
            file_flag = AUX_FILE_FLAG
        else:
            raise ValueError("RID invalido: file debe ser main o aux")
        if not 0 <= payload.page_id <= RID_PAGE_MASK or not 0 <= payload.slot_id <= RID_SLOT_MASK:
            raise ValueError("RID fuera del rango empaquetable")
        return (file_flag << (RID_PAGE_BITS + RID_SLOT_BITS)) | (payload.page_id << RID_SLOT_BITS) | payload.slot_id

    def _unpack_leaf_payload(self, payload: int) -> Any:
        if self.header.is_clustered or payload == EMPTY_CHILD:
            return payload
        file_flag = payload >> (RID_PAGE_BITS + RID_SLOT_BITS)
        page_id = (payload >> RID_SLOT_BITS) & RID_PAGE_MASK
        slot_id = payload & RID_SLOT_MASK
        file_name = "aux" if file_flag == AUX_FILE_FLAG else "main"
        return RID(page_id, slot_id, file_name)

    def _find_leaf_pos(self, key: Any) -> int:
        if self.header.root_pos == EMPTY_CHILD:
            return EMPTY_CHILD
        pos = self.header.root_pos
        key = self._normalize_key(key)
        while True:
            node = self._read_node(pos)
            if node.isLeaf:
                return pos
            i = 0
            while i < node.fullness and key >= node.keys[i]:
                i += 1
            pos = node.childs[i]

    def _find_leaf_path(self, key: Any) -> List[Tuple[int, BplusNode]]:
        path = []
        if self.header.root_pos == EMPTY_CHILD:
            return path
        pos = self.header.root_pos
        key = self._normalize_key(key)
        while True:
            node = self._read_node(pos)
            path.append((pos, node))
            if node.isLeaf:
                return path
            i = 0
            while i < node.fullness and key >= node.keys[i]:
                i += 1
            pos = node.childs[i]

    def _min_leaf_keys(self) -> int:
        return (self.header.M + 1) // 2

    def _min_internal_keys(self) -> int:
        return self.header.M // 2

    def _first_key(self, page_id: int) -> Any:
        node = self._read_node(page_id)
        while not node.isLeaf:
            node = self._read_node(node.childs[0])
        if not node.keys:
            return None
        return node.keys[0]

    def _refresh_internal_node(self, node: BplusNode) -> None:
        if node.isLeaf:
            return
        children = node.childs[:node.fullness + 1]
        node.keys = [self._first_key(child) for child in children[1:]]
        node.fullness = len(node.keys)
        node.childs = children

    def _refresh_path(self, path: List[Tuple[int, BplusNode]]) -> None:
        for pos, node in reversed(path):
            if not node.isLeaf:
                self._refresh_internal_node(node)
                self._write_node(pos, node)

    def _set_clean_state(self) -> None:
        self.header.overflow_state = False
        self.header.underflow_state = False
        self.header.exception_pos = EMPTY_CHILD
        self._write_header()

    def _insert_in_parent(
        self,
        path: List[Tuple[int, BplusNode]],
        left_pos: int,
        promoted_key: Any,
        right_pos: int,
    ) -> None:
        if not path:
            root_pos = self._allocate_node()
            root = BplusNode(
                fullness=1,
                childs=[left_pos, right_pos],
                keys=[promoted_key],
                isLeaf=False,
                nextLeaf=EMPTY_CHILD,
            )
            self._write_node(root_pos, root)
            self.header.root_pos = root_pos
            self._write_header()
            return

        parent_pos, parent = path.pop()
        children = parent.childs[:parent.fullness + 1]
        insert_at = children.index(left_pos) + 1
        children.insert(insert_at, right_pos)
        parent.childs = children
        parent.keys = [self._first_key(child) for child in children[1:]]
        parent.fullness = len(parent.keys)

        if parent.fullness <= self.header.M:
            self._write_node(parent_pos, parent)
            return

        promote_index = parent.fullness // 2
        promote_key = parent.keys[promote_index]
        left_keys = parent.keys[:promote_index]
        right_keys = parent.keys[promote_index + 1:]
        left_children = children[:promote_index + 1]
        right_children = children[promote_index + 1:]

        parent.keys = left_keys
        parent.childs = left_children
        parent.fullness = len(left_keys)
        right = BplusNode(
            fullness=len(right_keys),
            childs=right_children,
            keys=right_keys,
            isLeaf=False,
            nextLeaf=EMPTY_CHILD,
        )
        right_pos = self._allocate_node()
        self._write_node(parent_pos, parent)
        self._write_node(right_pos, right)
        self._insert_in_parent(path, parent_pos, promote_key, right_pos)

    def add(self, key: Any, payload: Any) -> bool:
        key = self._normalize_key(key)
        payload = self._pack_leaf_payload(payload)
        if self.header.root_pos == EMPTY_CHILD:
            root_pos = self._allocate_node()
            root = BplusNode(
                fullness=1,
                childs=[payload] + [EMPTY_CHILD] * self.header.M,
                keys=[key],
                isLeaf=True,
                nextLeaf=EMPTY_CHILD,
            )
            self._write_node(root_pos, root)
            self.header.root_pos = root_pos
            self.header.min_node_pos = root_pos
            self._write_header()
            return True

        path = self._find_leaf_path(key)
        leaf_pos, leaf = path[-1]
        parent_path = path[:-1]
        if key in leaf.keys:
            return False

        index = 0
        while index < leaf.fullness and leaf.keys[index] < key:
            index += 1
        leaf.keys.insert(index, key)
        leaf.childs.insert(index, payload)
        leaf.fullness += 1

        if leaf.fullness <= self.header.M:
            leaf.childs = leaf.childs[:leaf.fullness] + [EMPTY_CHILD]
            self._write_node(leaf_pos, leaf)
            self._refresh_path(parent_path)
            self._set_clean_state()
            return True

        self.header.overflow_state = True
        self.header.exception_pos = leaf_pos
        self._write_header()
        split_at = (self.header.M + 1) // 2
        right_keys = leaf.keys[split_at:]
        right_childs = leaf.childs[split_at:leaf.fullness]
        left_keys = leaf.keys[:split_at]
        left_childs = leaf.childs[:split_at]

        right_pos = self._allocate_node()
        right = BplusNode(
            fullness=len(right_keys),
            childs=right_childs + [EMPTY_CHILD],
            keys=right_keys,
            isLeaf=True,
            nextLeaf=leaf.nextLeaf,
        )
        leaf.keys = left_keys
        leaf.childs = left_childs + [EMPTY_CHILD]
        leaf.fullness = len(left_keys)
        leaf.nextLeaf = right_pos

        self._write_node(leaf_pos, leaf)
        self._write_node(right_pos, right)
        self._insert_in_parent(parent_path, leaf_pos, right.keys[0], right_pos)
        self._set_clean_state()
        return True

    # en el header del archivo te indica en donde ocurrio la excepcion
    def split(self):
        if self.header.exception_pos == EMPTY_CHILD:
            return False
        return True

    def handle_underflow(self, path=None):
        if path is None:
            return False
        return self._rebalance_after_delete(path)

    def borrow(self):
        pass

    def fusion(self):
        pass
    
    def insert(self, key: Any, payload: Any) -> bool:
        return self.add(key, payload)

    def search(self, key: Any):
        key = self._normalize_key(key)
        leaf_pos = self._find_leaf_pos(key)
        if leaf_pos == EMPTY_CHILD:
            return None
        leaf = self._read_node(leaf_pos)
        for stored_key, payload in zip(leaf.keys, leaf.childs):
            if stored_key == key:
                return self._unpack_leaf_payload(payload)
        return None

    def _leftmost_leaf_pos(self) -> int:
        if self.header.root_pos == EMPTY_CHILD:
            return EMPTY_CHILD
        pos = self.header.root_pos
        node = self._read_node(pos)
        while not node.isLeaf:
            pos = node.childs[0]
            node = self._read_node(pos)
        return pos

    def _leaf_entries(self) -> List[Tuple[Any, int]]:
        entries = []
        pos = self._leftmost_leaf_pos()
        while pos != EMPTY_CHILD:
            node = self._read_node(pos)
            for key, payload in zip(node.keys, node.childs[:node.fullness]):
                entries.append((key, payload))
            pos = node.nextLeaf
        return entries

    def _reset_tree_storage(self) -> None:
        self.header.root_pos = EMPTY_CHILD
        self.header.min_node_pos = EMPTY_CHILD
        self.header.overflow_state = False
        self.header.underflow_state = False
        self.header.exception_pos = EMPTY_CHILD
        self.header.number_pages = 1
        self._write_header()
        self._fh.truncate(self.header.page_size)
        self._fh.flush()

    def _rebalance_after_delete(self, path: List[Tuple[int, BplusNode]]) -> None:
        if not path:
            return

        pos, node = path[-1]
        if len(path) == 1:
            if not node.isLeaf and node.fullness == 0:
                self.header.root_pos = node.childs[0] if node.childs else EMPTY_CHILD
            if node.isLeaf and node.fullness == 0:
                self.header.root_pos = EMPTY_CHILD
                self.header.min_node_pos = EMPTY_CHILD
            self._write_header()
            return

        min_keys = self._min_leaf_keys() if node.isLeaf else self._min_internal_keys()
        if node.fullness >= min_keys:
            self._write_node(pos, node)
            self._refresh_path(path[:-1])
            return

        parent_pos, parent = path[-2]
        siblings = parent.childs[:parent.fullness + 1]
        node_index = siblings.index(pos)

        left_pos = siblings[node_index - 1] if node_index > 0 else EMPTY_CHILD
        right_pos = siblings[node_index + 1] if node_index + 1 < len(siblings) else EMPTY_CHILD
        left = self._read_node(left_pos) if left_pos != EMPTY_CHILD else None
        right = self._read_node(right_pos) if right_pos != EMPTY_CHILD else None

        if left is not None and left.fullness > min_keys:
            if node.isLeaf:
                node.keys.insert(0, left.keys.pop())
                node.childs.insert(0, left.childs.pop(left.fullness - 1))
                left.fullness -= 1
                node.fullness += 1
                left.childs = left.childs[:left.fullness] + [EMPTY_CHILD]
                node.childs = node.childs[:node.fullness] + [EMPTY_CHILD]
            else:
                left_children = left.childs[:left.fullness + 1]
                node_children = node.childs[:node.fullness + 1]
                moved_child = left_children.pop()
                node_children.insert(0, moved_child)
                left.childs = left_children
                node.childs = node_children
                self._refresh_internal_node(left)
                self._refresh_internal_node(node)
            self._write_node(left_pos, left)
            self._write_node(pos, node)
            self._refresh_path(path[:-1])
            return

        if right is not None and right.fullness > min_keys:
            if node.isLeaf:
                node.keys.append(right.keys.pop(0))
                node.childs.insert(node.fullness, right.childs.pop(0))
                right.fullness -= 1
                node.fullness += 1
                right.childs = right.childs[:right.fullness] + [EMPTY_CHILD]
                node.childs = node.childs[:node.fullness] + [EMPTY_CHILD]
            else:
                right_children = right.childs[:right.fullness + 1]
                node_children = node.childs[:node.fullness + 1]
                moved_child = right_children.pop(0)
                node_children.append(moved_child)
                right.childs = right_children
                node.childs = node_children
                self._refresh_internal_node(right)
                self._refresh_internal_node(node)
            self._write_node(right_pos, right)
            self._write_node(pos, node)
            self._refresh_path(path[:-1])
            return

        if left is not None:
            target_pos, target, source_pos, source = left_pos, left, pos, node
            remove_index = node_index
        else:
            target_pos, target, source_pos, source = pos, node, right_pos, right
            remove_index = node_index + 1

        if target.isLeaf:
            target.keys.extend(source.keys)
            target.childs = target.childs[:target.fullness] + source.childs[:source.fullness] + [EMPTY_CHILD]
            target.fullness = len(target.keys)
            target.nextLeaf = source.nextLeaf
        else:
            target.childs = target.childs[:target.fullness + 1] + source.childs[:source.fullness + 1]
            self._refresh_internal_node(target)
        self._write_node(target_pos, target)

        parent_children = parent.childs[:parent.fullness + 1]
        parent_children.pop(remove_index)
        parent.childs = parent_children
        self._refresh_internal_node(parent)
        self._write_node(parent_pos, parent)
        path[-2] = (parent_pos, parent)
        self._rebalance_after_delete(path[:-1])

    def delete(self, key: Any) -> bool:
        key = self._normalize_key(key)
        entries = self._leaf_entries()
        kept = [(stored_key, payload) for stored_key, payload in entries if stored_key != key]
        if len(kept) == len(entries):
            return False

        self._reset_tree_storage()
        for stored_key, payload in kept:
            self.add(stored_key, payload)
        self.header.min_node_pos = self._leftmost_leaf_pos()
        self._set_clean_state()
        return True

    def close(self):
        self._write_header()
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        
