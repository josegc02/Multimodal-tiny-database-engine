"""Catálogo explícito de storages abiertos e índices de igualdad vigentes."""

from dataclasses import dataclass, field
import math

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
    storage: object
    indexes: dict[str, RegisteredIndex] = field(default_factory=dict)
    statistics: TableStats | None = None

    def analyze(self):
        """Estadísticas explícitas; hasta 1024 valores distintos por columna.

        El límite subestima cardinalidades grandes de forma conservadora.
        Se ejecuta al registrar/refrescar, nunca dentro de explain().
        """
        distinct = {name: set() for name in self.storage.schema.fields}
        count = 0
        for _, row in self.storage.scan():
            count += 1
            for name, values in distinct.items():
                if len(values) < 1024:
                    values.add(row[name])
        per_page = max(1, (self.storage.page_size - PAGE_HEADER_SIZE) // (self.storage.schema.record_size + SLOT_SIZE))
        pages = getattr(self.storage, "num_pages", None)
        if pages is None:
            pages = getattr(self.storage, "num_pages_main", 0) + getattr(self.storage, "num_pages_aux", 0)
        self.statistics = TableStats(count, max(pages, math.ceil(count / per_page)),
                                     {name: len(values) for name, values in distinct.items()})

    def index_info(self):
        from dataclasses import replace
        return [replace(binding.metadata, valid=binding.valid)
                for binding in self.indexes.values()]

    def invalidate_indexes(self):
        for binding in self.indexes.values():
            binding.valid = False

    def refresh_indexes(self):
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

    def table(self, name: str) -> TableBinding:
        try:
            return self.tables[name]
        except KeyError:
            raise SQLSemanticError(f"La tabla {name!r} no existe") from None
