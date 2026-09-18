"""Catálogo explícito de storages abiertos e índices de igualdad vigentes."""

from dataclasses import dataclass, field

from engine.query.errors import SQLSemanticError


@dataclass
class RegisteredIndex:
    index: object
    valid: bool = False


@dataclass
class TableBinding:
    storage: object
    indexes: dict[str, RegisteredIndex] = field(default_factory=dict)

    def invalidate_indexes(self):
        for binding in self.indexes.values():
            binding.valid = False

    def refresh_indexes(self):
        self.invalidate_indexes()
        for name, binding in self.indexes.items():
            binding.index.bulk_load_from_storage(self.storage, name, replace=True)
            binding.valid = True


class Catalog:
    """No abre/cierra archivos: el llamador controla el ciclo de vida del storage.

    Los nombres deben coincidir con los del AST (minúsculas para nombres SQL sin
    comillas). Tras cambios directos en el storage se deben invalidar/reconstruir
    los índices; SQLExecutor lo hace automáticamente para sus propias escrituras.
    """

    def __init__(self):
        self.tables: dict[str, TableBinding] = {}

    def register_table(self, name: str, storage, indexes: dict | None = None) -> TableBinding:
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
            if not all(callable(getattr(index, method, None)) for method in ("search", "bulk_load_from_storage")):
                raise SQLSemanticError("El índice requiere search() y bulk_load_from_storage()")
            binding.indexes[column] = RegisteredIndex(index)
        binding.refresh_indexes()
        self.tables[name] = binding
        return binding

    def table(self, name: str) -> TableBinding:
        try:
            return self.tables[name]
        except KeyError:
            raise SQLSemanticError(f"La tabla {name!r} no existe") from None
