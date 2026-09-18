"""B+ agrupado: registros completos en hojas ordenadas por clave primaria única."""

import math
import struct

from engine.indexes.bplus_tree import (
    BPlusTree, BplusNode, EMPTY_CHILD, NODE_HEADER_FORMAT, NODE_HEADER_SIZE,
)


class BPlusTreeClustered(BPlusTree):
    """insert(record), search(key), delete(key) y range_search(lower, upper).

    Las hojas son las páginas de datos; split/merge mueven registros completos.
    No expone RIDs estables. Las claves duplicadas retornan False en insert.
    """
    leaf_records = True

    def __init__(self, filepath, schema_def, key_field, M=4, page_size=4096):
        super().__init__(filepath, schema_def, key_field, M, page_size, is_clustered=True)

    def _configure_node_layout(self):
        super()._configure_node_layout()
        self.leaf_size = NODE_HEADER_SIZE + self.header.M * (self.key_size + self.schema.record_size)
        if self.leaf_size > self.header.page_size:
            raise ValueError("Los registros de la hoja no caben en una página con el M indicado")

    def _pack_leaf_payload(self, payload):
        if not isinstance(payload, dict) or set(payload) != set(self.schema.fields):
            raise ValueError("El registro debe contener todas las columnas del schema")
        for name, kind, size in zip(self.schema.fields, self.schema.types, self.schema.sizes):
            value = payload[name]
            if kind == "int" and (type(value) is not int or not -(1 << 63) <= value < (1 << 63)):
                raise ValueError(f"Entero inválido: {name}")
            if kind == "float" and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError(f"Float inválido: {name}")
            if kind == "str" and (not isinstance(value, str) or "\x00" in value or len(value.encode("utf-8")) > size):
                raise ValueError(f"String inválido o demasiado largo: {name}")
        return self.schema.deserialize(self.schema.serialize(payload))

    def _unpack_leaf_payload(self, payload):
        return dict(payload)

    def insert(self, record):
        record = self._pack_leaf_payload(record)
        return super().add(record[self.key_field], record)

    def add(self, key, record):
        record = self._pack_leaf_payload(record)
        if self._normalize_key(key) != record[self.key_field]:
            raise ValueError("La clave no coincide con el registro")
        return super().add(key, record)

    def _write_node(self, page_id, node):
        if not node.isLeaf:
            return super()._write_node(page_id, node)
        self._validate_node_shape(node)
        data = bytearray(struct.pack(NODE_HEADER_FORMAT, node.fullness, True, node.nextLeaf))
        for key, record in zip(node.keys, node.childs[:node.fullness]):
            data.extend(self._serialize_key(key))
            data.extend(self.schema.serialize(record))
        data.extend(b"\x00" * (self.header.page_size - len(data)))
        self._fh.seek(self._page_offset(page_id))
        self._fh.write(data)
        self._fh.flush()

    def _read_node(self, page_id):
        if not 1 <= page_id < self.header.number_pages:
            raise ValueError("Puntero de nodo fuera del archivo")
        self._fh.seek(self._page_offset(page_id))
        data = self._fh.read(self.header.page_size)
        if len(data) != self.header.page_size:
            raise ValueError("Página B+ truncada")
        count, leaf, following = struct.unpack_from(NODE_HEADER_FORMAT, data)
        if not leaf:
            return super()._read_node(page_id)
        if not 0 <= count <= self.header.M:
            raise ValueError("Cantidad de registros inválida")
        keys, records, offset = [], [], NODE_HEADER_SIZE
        for _ in range(count):
            keys.append(self._deserialize_key(data[offset:offset + self.key_size]))
            offset += self.key_size
            records.append(self.schema.deserialize(data[offset:offset + self.schema.record_size]))
            offset += self.schema.record_size
        return BplusNode(count, records + [EMPTY_CHILD], keys, True, following)

    def range_search(self, lower=None, upper=None, **kwargs):
        return [record for _, record in self.iter_range(lower, upper, **kwargs)]

    def scan(self):
        """Itera registros en orden de clave sin materializar el árbol."""
        for _, record in self.iter_range():
            yield record
