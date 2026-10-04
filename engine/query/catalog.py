"""Catálogo explícito de storages abiertos y de sus índices vigentes."""

from dataclasses import dataclass, field
import math
import threading

from engine.query.errors import SQLIntegrityError, SQLSemanticError
from engine.query.planner import IndexInfo, TableStats
from engine.storage.heap_file import PAGE_HEADER_SIZE, SLOT_SIZE


@dataclass(frozen=True)
class ForeignKey:
    """Llave foránea de una columna hacia la clave primaria de otra tabla."""
    name: str          # p. ej. "alumnos_carrera_id_fkey"
    table: str         # tabla hija
    column: str
    ref_table: str     # tabla padre
    ref_column: str    # su clave primaria
    on_delete: str = "RESTRICT"


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
    # Hay índices secundarios que deben reconstruirse al terminar la escritura.
    _rebuild_pending: bool = field(default=False, repr=False, compare=False)
    # Clave primaria (una columna) y nombre de su restricción, p. ej. "alumnos_pkey".
    primary_key: str | None = None
    primary_key_name: str | None = None
    foreign_keys: list = field(default_factory=list)
    # Auto-analyze (como PostgreSQL): estadísticas exactas tras
    # ANALYZE_BASE + ANALYZE_FRACTION * filas cambios desde el último analyze.
    _changes_since_analyze: int = field(default=0, repr=False, compare=False)

    ANALYZE_BASE = 50
    ANALYZE_FRACTION = 0.10

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

    def ensure_unique(self, record):
        """Lanza SQLIntegrityError si la clave primaria de `record` ya existe.

        Se llama con el lock X de la fila tomado, así que dos transacciones no
        pueden insertar la misma clave a la vez.
        """
        if self.primary_key is None:
            return
        value = record[self.primary_key]
        if self._key_exists(value):
            raise SQLIntegrityError(
                f'llave duplicada viola la restricción de unicidad "{self.primary_key_name}": '
                f"ya existe la llave ({self.primary_key})=({value})")

    def _key_exists(self, value):
        with self.latch:
            column = self.primary_key
            registered = self.indexes.get(column)
            if registered is not None and registered.valid:
                return any(self.storage.get(rid) is not None for rid in registered.index.search(value))
            if getattr(self.storage, "key_field", None) == column and callable(
                    getattr(self.storage, "search_by_key", None)):
                return bool(self.storage.search_by_key(value))
            return any(record[column] == value for _, record in self.storage.scan())

    def rows_with(self, column, value):
        """(RID, registro) con `column == value`, usando un índice vigente si existe."""
        with self.latch:
            registered = self.indexes.get(column)
            if registered is not None and registered.valid:
                found = [(rid, self.storage.get(rid)) for rid in registered.index.search(value)]
                return [(rid, record) for rid, record in found
                        if record is not None and record[column] == value]
            return [(rid, record) for rid, record in self.storage.scan() if record[column] == value]

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
        self.statistics = TableStats(count, self._pages(count),
                                     {name: len(values) for name, values in distinct.items()},
                                     bounds)
        self._changes_since_analyze = 0

    def _pages(self, rows):
        per_page = max(1, (self.storage.page_size - PAGE_HEADER_SIZE) // (self.storage.schema.record_size + SLOT_SIZE))
        pages = getattr(self.storage, "num_pages", None)
        if pages is None:
            pages = getattr(self.storage, "num_pages_main", 0) + getattr(self.storage, "num_pages_aux", 0)
        return max(pages, math.ceil(rows / per_page))

    def _adjust_statistics(self, delta, record):
        """Actualiza cardinalidad, páginas y (mín, máx) sin recorrer la tabla.

        Los valores distintos no se pueden mantener exactos fila por fila: se
        conservan como estimación y se recalculan con analyze() cuando cambió
        una fracción de la tabla (costo amortizado O(1) por fila).
        """
        stats = self.statistics
        if stats is None:
            return
        self._changes_since_analyze += 1
        if self._changes_since_analyze > self.ANALYZE_BASE + self.ANALYZE_FRACTION * stats.rows:
            self.analyze()
            return
        rows = max(0, stats.rows + delta)
        distinct = {name: (min(max(count, 1), rows) if rows else 0)
                    for name, count in stats.distinct_values.items()}
        if self.primary_key in distinct:
            # La clave primaria es única: tiene tantos valores distintos como filas.
            distinct[self.primary_key] = min(rows, 1024)
        bounds = dict(stats.value_bounds)
        if delta > 0:
            schema = self.storage.schema
            for name, kind in zip(schema.fields, schema.types):
                if kind in ("int", "float"):
                    low, high = bounds.get(name, (record[name], record[name]))
                    bounds[name] = (min(low, record[name]), max(high, record[name]))
        self.statistics = TableStats(rows, self._pages(rows), distinct, bounds)

    def _secondary_indexes(self):
        """Índices con estructura propia (el primario agrupado ES la tabla)."""
        return [(column, registered) for column, registered in self.indexes.items()
                if not getattr(registered.index, "self_maintained", False)]

    def _incremental(self):
        """¿Se pueden actualizar los índices fila por fila?

        Solo si el storage tiene RIDs estables (HeapFile): en el secuencial y en
        el B+ agrupado una inserción o reorganización mueve los RIDs de otras
        filas, así que sus índices secundarios se reconstruyen al final.
        """
        return getattr(self.storage, "stable_rids", False) and all(
            callable(getattr(registered.index, "insert", None))
            and callable(getattr(registered.index, "delete", None))
            for _, registered in self._secondary_indexes())

    def record_inserted(self, rid, record):
        """Mantiene índices y estadísticas tras insertar `record` en `rid`."""
        with self.latch:
            self._adjust_statistics(+1, record)
            self._maintain(lambda index, key: index.insert(key, rid), record)

    def record_deleted(self, rid, record):
        """Mantiene índices y estadísticas tras eliminar `record` de `rid`."""
        with self.latch:
            self._adjust_statistics(-1, record)
            self._maintain(lambda index, key: index.delete(key, rid), record)

    def _maintain(self, operation, record):
        secondary = self._secondary_indexes()
        if not secondary:
            return
        if self._incremental() and not self._rebuild_pending:
            try:
                for column, registered in secondary:
                    operation(registered.index, record[column])
                return
            except Exception:
                pass  # el índice quedó a medias: se reconstruye al final
        self._rebuild_pending = True
        for _, registered in secondary:
            registered.valid = False

    def finish_write(self):
        """Fin de una sentencia o de un rollback: reconstruye lo pendiente."""
        with self.latch:
            if self._rebuild_pending:
                self.refresh_indexes()

    def index_info(self):
        from dataclasses import replace
        return [replace(binding.metadata, valid=binding.valid)
                for binding in self.indexes.values()]

    def invalidate_indexes(self):
        with self.latch:
            for binding in self.indexes.values():
                binding.valid = False

    def refresh_indexes(self):
        """Reconstrucción completa (O(N)): al registrar índices o tras cambios
        que movieron RIDs. Las escrituras normales usan record_inserted/deleted."""
        with self.latch:
            self.invalidate_indexes()
            for name, binding in self.indexes.items():
                binding.index.bulk_load_from_storage(self.storage, name, replace=True)
                binding.valid = True
            self._rebuild_pending = False
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
                       *, statistics: TableStats | None = None,
                       primary_key: str | None = None) -> TableBinding:
        if not isinstance(name, str) or not name or name in self.tables:
            raise SQLSemanticError(f"Nombre de tabla inválido o repetido: {name!r}")
        for method in ("scan", "get", "insert", "delete"):
            if not callable(getattr(storage, method, None)):
                raise SQLSemanticError(f"El storage no ofrece {method}()")
        if not hasattr(storage, "schema"):
            raise SQLSemanticError("El storage debe exponer su schema")
        binding = TableBinding(storage)
        if primary_key is not None:
            if primary_key not in storage.schema.fields:
                raise SQLSemanticError(f"Clave primaria inexistente: {primary_key}")
            binding.primary_key = primary_key
            binding.primary_key_name = f"{name}_pkey"
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

    def add_foreign_key(self, foreign_key: ForeignKey) -> None:
        """Valida y registra una llave foránea (la columna padre debe ser su PRIMARY KEY)."""
        child = self.table(foreign_key.table)
        parent = self.table(foreign_key.ref_table)
        if parent.primary_key != foreign_key.ref_column:
            raise SQLSemanticError(
                f"La columna referenciada {foreign_key.ref_table}.{foreign_key.ref_column} "
                "debe ser la clave primaria de su tabla")
        child_types = dict(zip(child.storage.schema.fields, child.storage.schema.types))
        parent_types = dict(zip(parent.storage.schema.fields, parent.storage.schema.types))
        if child_types.get(foreign_key.column) != parent_types[foreign_key.ref_column]:
            raise SQLSemanticError(
                f"La llave foránea {foreign_key.name} une tipos distintos: "
                f"{child_types.get(foreign_key.column)} y {parent_types[foreign_key.ref_column]}")
        child.foreign_keys.append(foreign_key)

    def referencing(self, table: str) -> list:
        """Llaves foráneas (de cualquier tabla) que apuntan a `table`."""
        return [foreign_key for binding in self.tables.values()
                for foreign_key in binding.foreign_keys if foreign_key.ref_table == table]

    def table(self, name: str) -> TableBinding:
        try:
            return self.tables[name]
        except KeyError:
            raise SQLSemanticError(f"La tabla {name!r} no existe") from None
