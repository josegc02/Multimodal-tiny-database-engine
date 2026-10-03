"""Catálogo explícito de storages abiertos e índices de igualdad vigentes."""

from dataclasses import dataclass, field
import math
import threading

from engine.query.errors import SQLSemanticError
from engine.query.planner import IndexInfo, TableStats
from engine.storage.heap_file import PAGE_HEADER_SIZE, SLOT_SIZE


@dataclass
class RegisteredIndex:
    index: object
    valid: bool = False
    metadata: IndexInfo | None = None


@dataclass
class TableBinding:
    """Storage + índices de una tabla.

    `latch` protege la consistencia física entre storage e índices (una
    modificación y la actualización de sus índices ocurren juntas). Es corto:
    nunca se retiene mientras se espera un lock lógico del LockManager.
    """
    storage: object
    indexes: dict[str, RegisteredIndex] = field(default_factory=dict)
    statistics: TableStats | None = None
    latch: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def locate(self, rid, record):
        """RID actual de `record`, o None si ya no existe.

        Los RIDs del SequentialFile cambian con inserciones y reorganizaciones,
        así que si el RID guardado ya no contiene el registro se busca por clave
        (secuencial) o por contenido (heap).
        """
        with self.latch:
            storage = self.storage
            if rid is not None and storage.get(rid) == record:
                return rid
            key_field = getattr(storage, "key_field", None)
            if key_field is not None and callable(getattr(storage, "search_by_key", None)):
                candidates = storage.search_by_key(record[key_field])
            else:
                candidates = storage.scan()
            for current_rid, current in candidates:
                if current == record:
                    return current_rid
            return None

    def analyze(self):
        """Estadísticas explícitas; hasta 1024 valores distintos por columna y
        (mínimo, máximo) de las columnas numéricas.

        El límite subestima cardinalidades grandes de forma conservadora.
        Se ejecuta al registrar/refrescar, nunca dentro de explain().
        """
        schema = self.storage.schema
        distinct = {name: set() for name in schema.fields}
        numeric = [name for name, kind in zip(schema.fields, schema.types) if kind in ("int", "float")]
        bounds = {}
        count = 0
        for _, row in self.storage.scan():
            count += 1
            for name, values in distinct.items():
                if len(values) < 1024:
                    values.add(row[name])
            for name in numeric:
                value = row[name]
                if name in bounds:
                    low, high = bounds[name]
                    bounds[name] = (min(low, value), max(high, value))
                else:
                    bounds[name] = (value, value)
        per_page = max(1, (self.storage.page_size - PAGE_HEADER_SIZE) // (self.storage.schema.record_size + SLOT_SIZE))
        pages = getattr(self.storage, "num_pages", None)
        if pages is None:
            pages = getattr(self.storage, "num_pages_main", 0) + getattr(self.storage, "num_pages_aux", 0)
        self.statistics = TableStats(count, max(pages, math.ceil(count / per_page)),
                                     {name: len(values) for name, values in distinct.items()},
                                     bounds)

    def index_info(self):
        from dataclasses import replace
        return [replace(binding.metadata, valid=binding.valid)
                for binding in self.indexes.values()]

    def invalidate_indexes(self):
        with self.latch:
            for binding in self.indexes.values():
                binding.valid = False

    def refresh_indexes(self):
        with self.latch:
            self.invalidate_indexes()
            for name, binding in self.indexes.items():
                binding.index.bulk_load_from_storage(self.storage, name, replace=True)
                binding.valid = True
            self.analyze()


class Catalog:
    """No abre/cierra archivos: el llamador controla el ciclo de vida del storage.

    Los nombres deben coincidir con los del AST (minúsculas para nombres SQL sin
    comillas). Tras cambios directos en el storage se deben invalidar/reconstruir
    los índices; SQLExecutor lo hace automáticamente para sus propias escrituras.
    """

    def __init__(self):
        self.tables: dict[str, TableBinding] = {}

    def register_table(self, name: str, storage, indexes: dict | None = None,
                       *, statistics: TableStats | None = None) -> TableBinding:
        if not isinstance(name, str) or not name or name in self.tables:
            raise SQLSemanticError(f"Nombre de tabla inválido o repetido: {name!r}")
        for method in ("scan", "get", "insert", "delete"):
            if not callable(getattr(storage, method, None)):
                raise SQLSemanticError(f"El storage no ofrece {method}()")
        if not hasattr(storage, "schema"):
            raise SQLSemanticError("El storage debe exponer su schema")
        binding = TableBinding(storage)
        for column, index in (indexes or {}).items():
            if column not in storage.schema.fields:
                raise SQLSemanticError(f"Columna de índice inexistente: {column}")
            metadata = index if isinstance(index, IndexInfo) else IndexInfo(f"{name}.{column}", column, index)
            index = metadata.index
            if metadata.field != column:
                raise SQLSemanticError("El campo del índice no coincide con su registro")
            if not all(callable(getattr(index, method, None)) for method in ("search", "bulk_load_from_storage")):
                raise SQLSemanticError("El índice requiere search() y bulk_load_from_storage()")
            binding.indexes[column] = RegisteredIndex(index, metadata=metadata)
        binding.refresh_indexes()
        if statistics is not None:
            binding.statistics = statistics
        self.tables[name] = binding
        return binding

    def register_index(self, table_name: str, column: str, index,
                       metadata: IndexInfo) -> RegisteredIndex:
        """Registra y construye un índice sobre una tabla ya abierta."""
        binding = self.table(table_name)
        if column not in binding.storage.schema.fields:
            raise SQLSemanticError(f"Columna de índice inexistente: {column}")
        if column in binding.indexes:
            raise SQLSemanticError(f"Ya existe un índice para la columna {column!r}")
        if not isinstance(metadata, IndexInfo):
            raise SQLSemanticError("Los metadatos del índice no son válidos")
        if metadata.field != column or metadata.index is not index:
            raise SQLSemanticError("El campo del índice no coincide con su registro")
        if not all(callable(getattr(index, method, None))
                   for method in ("search", "bulk_load_from_storage")):
            raise SQLSemanticError("El índice requiere search() y bulk_load_from_storage()")

        registered = RegisteredIndex(index, metadata=metadata)
        binding.indexes[column] = registered
        try:
            binding.refresh_indexes()
        except Exception:
            del binding.indexes[column]
            raise
        return registered

    def table(self, name: str) -> TableBinding:
        try:
            return self.tables[name]
        except KeyError:
            raise SQLSemanticError(f"La tabla {name!r} no existe") from None
