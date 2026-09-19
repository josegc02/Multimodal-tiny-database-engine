"""Encapsula el motor de base de datos para el frontend.

Une:
- Catalog con tablas de demo
- LockManager + TransactionManager
- SQLExecutor (para SELECT)
- StatementExecutor (para INSERT/DELETE/BEGIN/COMMIT)
"""

from __future__ import annotations

import os

from engine.concurrency.lock_manager import LockManager
from engine.concurrency.transaction_manager import TransactionManager
from engine.query.ast import (
    CreateIndexStatement,
    CreateTableStatement,
    DeleteStatement,
    InsertStatement,
    SelectStatement,
    TransactionStatement,
)
from engine.query.catalog import Catalog
from engine.query.planner import IndexInfo
from engine.query.sql_executor import SQLExecutor
from engine.query.statement_executor import StatementExecutor
from engine.query.parser import parse_script
from engine.indexes import ExtendibleHash
from engine.indexes.bplus_tree_unclustered import BPlusTreeUnclustered
from engine.storage.heap_file import HeapFile


# Ruta donde se guardan los archivos de demo
DEMO_DIR = "demo_data"


class Resultado:
    """Resultado de una ejecucion SQL.

    Alguno de estos campos estara lleno:
    - columnas + filas: para SELECT
    - mensaje: para INSERT/DELETE/BEGIN/COMMIT
    - error: si algo fallo
    - plan: el LogicalPlan para el panel de plan
    """

    def __init__(self, columnas=None, filas=None, mensaje=None,
                 plan=None, error=None):
        self.columnas = columnas or []
        self.filas = filas or []
        self.mensaje = mensaje
        self.plan = plan
        self.error = error

    @property
    def tiene_tabla(self):
        return bool(self.columnas)

    @property
    def tiene_error(self):
        return self.error is not None


class Motor:
    """Fachada del motor para el frontend."""

    def __init__(self):
        self.catalog = Catalog()
        self.lock_manager = LockManager()
        self.transaction_manager = TransactionManager(
            self.lock_manager, storage=self.catalog
        )
        self.sql_executor = SQLExecutor(self.catalog)
        self.statement_executor = StatementExecutor(
            transaction_manager=self.transaction_manager,
            lock_manager=self.lock_manager,
            storage=self.catalog,
        )
        self._cargar_tablas_demo()

    # ------------------------------------------------------------------
    # Carga de tablas de demo
    # ------------------------------------------------------------------

    def _cargar_tablas_demo(self):
        """Crea tablas de ejemplo para la demo."""
        os.makedirs(DEMO_DIR, exist_ok=True)

        # --- Tabla cuentas ---
        path_cuentas = os.path.join(DEMO_DIR, "cuentas.db")
        self._eliminar_archivos_tabla(path_cuentas)

        schema_cuentas = [
            ("id", "int"),
            ("nombre", "str", 20),
            ("saldo", "int"),
        ]
        storage_cuentas = HeapFile(path_cuentas, schema_cuentas)
        storage_cuentas.insert({"id": 1, "nombre": "Ana", "saldo": 1000})
        storage_cuentas.insert({"id": 2, "nombre": "Bob", "saldo": 500})
        storage_cuentas.insert({"id": 3, "nombre": "Carlos", "saldo": 750})

        self.catalog.register_table("cuentas", storage_cuentas)

        # --- Tabla productos ---
        path_productos = os.path.join(DEMO_DIR, "productos.db")
        self._eliminar_archivos_tabla(path_productos)

        schema_productos = [
            ("id", "int"),
            ("nombre", "str", 30),
            ("precio", "int"),
        ]
        storage_productos = HeapFile(path_productos, schema_productos)
        storage_productos.insert({"id": 1, "nombre": "Laptop", "precio": 2500})
        storage_productos.insert({"id": 2, "nombre": "Mouse", "precio": 50})
        storage_productos.insert({"id": 3, "nombre": "Teclado", "precio": 150})

        self.catalog.register_table("productos", storage_productos)

    # ------------------------------------------------------------------
    # Ejecucion
    # ------------------------------------------------------------------

    @staticmethod
    def _eliminar_archivos_tabla(base_path):
        """Elimina archivos antiguos de una tabla demo."""
        root = base_path[:-3] if base_path.endswith(".db") else base_path
        for path in (f"{root}.db", f"{root}.main", f"{root}.aux"):
            if os.path.exists(path):
                os.remove(path)

    def ejecutar(self, sql: str) -> Resultado:
        """Ejecuta SQL y devuelve un Resultado.

        Acepta multiples sentencias separadas por ';'.
        Devuelve el resultado de la ULTIMA sentencia, y los mensajes
        de las anteriores concatenados.
        """
        sql = sql.strip()
        if not sql:
            return Resultado(error="La consulta esta vacia")

        try:
            sentencias = parse_script(sql)
        except Exception as e:
            return Resultado(error=f"Error de sintaxis: {e}")

        if not sentencias:
            return Resultado(error="No se encontro ninguna sentencia")

        mensajes = []
        ultimo_resultado = Resultado()

        for ast in sentencias:
            resultado = self._ejecutar_una(ast)
            if resultado.tiene_error:
                return resultado
            if resultado.mensaje:
                mensajes.append(resultado.mensaje)
            ultimo_resultado = resultado

        if mensajes:
            ultimo_resultado.mensaje = "\n".join(mensajes)

        return ultimo_resultado

    def _ejecutar_una(self, ast) -> Resultado:
        """Ejecuta una sola sentencia AST."""
        try:
            # --- Transacciones ---
            if isinstance(ast, TransactionStatement):
                mensaje = self.statement_executor.execute(ast)
                return Resultado(mensaje=mensaje)

            # --- DDL ---
            if isinstance(ast, CreateTableStatement):
                return Resultado(mensaje=self._crear_tabla(ast))
            if isinstance(ast, CreateIndexStatement):
                return Resultado(mensaje=self._crear_indice(ast))

            # --- INSERT / DELETE ---
            if isinstance(ast, (InsertStatement, DeleteStatement)):
                mensaje = self.statement_executor.execute(ast)
                return Resultado(mensaje=mensaje)

            # --- SELECT ---
            if isinstance(ast, SelectStatement):
                plan = self.sql_executor.planner.plan(ast)
                filas_iter = self.sql_executor.execute(plan)
                filas_dict = list(filas_iter)

                if filas_dict:
                    columnas = list(filas_dict[0].keys())
                    filas = [tuple(d.get(c) for c in columnas) for d in filas_dict]
                else:
                    columnas = self._columnas_del_plan(plan)
                    filas = []

                plan_explicado = self.sql_executor.optimizer.explain(plan)
                return Resultado(columnas=columnas, filas=filas, plan=plan_explicado)

            return Resultado(error=f"Sentencia no soportada: {type(ast).__name__}")

        except Exception as e:
            return Resultado(error=str(e))

    def _crear_tabla(self, statement: CreateTableStatement) -> str:
        """Crea un HeapFile y lo incorpora al catálogo de la sesión."""
        if statement.name in self.catalog.tables:
            raise ValueError(f"La tabla {statement.name!r} ya existe")
        fields = [column.name for column in statement.columns]
        if len(fields) != len(set(fields)):
            raise ValueError("La tabla contiene columnas repetidas")
        schema = []
        for column in statement.columns:
            definition = (column.name, column.type)
            if column.type == "str":
                definition += (column.size,)
            schema.append(definition)

        path = os.path.join(DEMO_DIR, f"{statement.name}.db")
        if os.path.exists(path):
            raise ValueError(f"Ya existe el archivo de la tabla {statement.name!r}")
        storage = HeapFile(path, schema)
        try:
            self.catalog.register_table(statement.name, storage)
        except Exception:
            storage.close()
            raise
        return f"Tabla {statement.name} creada"

    def _crear_indice(self, statement: CreateIndexStatement) -> str:
        """Crea, carga y registra un índice SQL sobre una tabla."""
        binding = self.catalog.table(statement.table)
        if statement.column not in binding.storage.schema.fields:
            raise ValueError(f"Columna de índice inexistente: {statement.column}")
        if statement.column in binding.indexes:
            raise ValueError(f"Ya existe un índice para la columna {statement.column!r}")
        if any(registered.metadata and registered.metadata.name == statement.name
               for table_binding in self.catalog.tables.values()
               for registered in table_binding.indexes.values()):
            raise ValueError(f"El índice {statement.name!r} ya existe")

        position = binding.storage.schema.fields.index(statement.column)
        key_type = binding.storage.schema.types[position]
        index_path = os.path.join(DEMO_DIR, f"{statement.table}_{statement.name}")
        if statement.method == "hash":
            index = ExtendibleHash(filepath=f"{index_path}.hash")
            metadata = IndexInfo(statement.name, statement.column, index)
        else:
            key_size = binding.storage.schema.sizes[position] if key_type == "str" else 64
            index = BPlusTreeUnclustered(
                f"{index_path}.bpt", key_type=key_type, key_size=key_size
            )
            metadata = IndexInfo(statement.name, statement.column, index, ordered=True)

        try:
            self.catalog.register_index(statement.table, statement.column, index, metadata)
        except Exception:
            index.close()
            raise
        return f"Índice {statement.name} creado sobre {statement.table}.{statement.column}"

    def _columnas_del_plan(self, plan):
        """Intenta extraer los nombres de columna del plan (para SELECT vacio)."""
        try:
            if plan.operation == "Project":
                columnas = plan.get("columns")
                if columnas:
                    return [label for label, _ in columnas]
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------

    def cerrar(self):
        """Cierra todos los storages e indices abiertos."""
        for nombre, binding in self.catalog.tables.items():
            # Cerrar storage
            try:
                if hasattr(binding.storage, "close"):
                    binding.storage.close()
            except Exception:
                pass

            # Cerrar indices
            for campo, reg in binding.indexes.items():
                try:
                    if hasattr(reg.index, "close"):
                        reg.index.close()
                except Exception:
                    pass