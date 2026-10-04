"""Encapsula el motor de base de datos para el frontend.

Modo demo: cada vez que se crea un Motor se vacía DEMO_DIR (solo los archivos
que genera el motor) y se crean las tablas de ejemplo. Nada sobrevive al
cierre de la aplicación; la capa de almacenamiento sí permite reabrir sus
archivos (ver los tests de reapertura de HeapFile, SequentialFile y B+).

Une:
- Catalog con tablas de demo
- LockManager + TransactionManager
- SQLExecutor (planes y algoritmos de consulta)
- StatementExecutor (SELECT/INSERT/DELETE/BEGIN/COMMIT con locks)
"""

from __future__ import annotations

import os
import shutil

from engine.concurrency.lock_manager import LockManager
from engine.concurrency.transaction_manager import TransactionManager
from engine.query.ast import (
    CopyStatement,
    CreateIndexStatement,
    CreateTableStatement,
    DeleteStatement,
    ExplainStatement,
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
from engine.indexes.bplus_tree import CHILD_SIZE, NODE_HEADER_SIZE
from engine.indexes.bplus_tree_unclustered import BPlusTreeUnclustered
from engine.storage.clustered_file import ClusteredBPlusFile
from engine.storage.heap_file import HeapFile
from engine.storage.sequential_file import SequentialFile


# Raíz del proyecto: base de las rutas relativas de COPY.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Carpeta de trabajo del modo demo (relativa a la raíz del proyecto, no al cwd).
DEMO_DIR = os.path.join(PROJECT_DIR, "demo_data")

# Archivos que genera el motor y que el modo demo elimina al iniciar.
_EXTENSIONES_MOTOR = (".db", ".main", ".aux", ".bpt", ".hash", ".idx", ".reorg", ".tmp")
_DIRECTORIOS_TEMPORALES = (".bplus-build-",)


class Resultado:
    """Resultado de una ejecucion SQL.

    Alguno de estos campos estara lleno:
    - columnas + filas: para SELECT y EXPLAIN (columna "QUERY PLAN")
    - mensaje: para INSERT/DELETE/COPY/BEGIN/COMMIT
    - error: si algo fallo
    - plan: líneas del QUERY PLAN (solo con EXPLAIN / EXPLAIN ANALYZE)
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
            query_executor=self.sql_executor,
            planner=self.sql_executor.planner,
            base_dir=PROJECT_DIR,
        )
        self._cerrado = False
        self._limpiar_directorio_demo()
        self._cargar_tablas_demo()

    # ------------------------------------------------------------------
    # Carga de tablas de demo
    # ------------------------------------------------------------------

    @staticmethod
    def _limpiar_directorio_demo():
        """Elimina los archivos de sesiones anteriores.

        No ignora errores: en Windows un archivo abierto por otra instancia no
        se puede borrar, y continuar reabriría datos viejos sin avisar.
        """
        os.makedirs(DEMO_DIR, exist_ok=True)
        errores = []
        for nombre in os.listdir(DEMO_DIR):
            ruta = os.path.join(DEMO_DIR, nombre)
            try:
                if os.path.isfile(ruta) and nombre.endswith(_EXTENSIONES_MOTOR):
                    os.remove(ruta)
                elif os.path.isdir(ruta) and nombre.startswith(_DIRECTORIOS_TEMPORALES):
                    shutil.rmtree(ruta)
            except OSError as exc:
                errores.append(f"{nombre}: {exc}")
        if errores:
            raise RuntimeError(
                "No se pudo limpiar la carpeta de la demo (¿hay otra instancia del frontend abierta?): "
                + "; ".join(errores)
            )

    def _cargar_tablas_demo(self):
        """Crea las tablas de ejemplo de la demo."""
        tablas = {
            "cuentas": ([("id", "int"), ("nombre", "str", 20), ("saldo", "int")],
                        [(1, "Ana", 1000), (2, "Bob", 500), (3, "Carlos", 750)]),
            "productos": ([("id", "int"), ("nombre", "str", 30), ("precio", "int")],
                          [(1, "Laptop", 2500), (2, "Mouse", 50), (3, "Teclado", 150)]),
        }
        for nombre, (schema, filas) in tablas.items():
            storage = HeapFile(os.path.join(DEMO_DIR, f"{nombre}.db"), schema)
            campos = [campo[0] for campo in schema]
            for fila in filas:
                storage.insert(dict(zip(campos, fila)))
            self.catalog.register_table(nombre, storage)

    # ------------------------------------------------------------------
    # Ejecucion
    # ------------------------------------------------------------------

    @staticmethod
    def _archivos_tabla(nombre):
        """Archivos que usaría una tabla según su método de almacenamiento."""
        base = os.path.join(DEMO_DIR, nombre)
        return (f"{base}.db", f"{base}.db.main", f"{base}.db.aux", f"{base}.bpt")

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

            # --- INSERT / DELETE / COPY ---
            if isinstance(ast, (InsertStatement, DeleteStatement, CopyStatement)):
                mensaje = self.statement_executor.execute(ast)
                return Resultado(mensaje=mensaje)

            # --- EXPLAIN [ANALYZE]: el plan se muestra solo cuando se pide ---
            if isinstance(ast, ExplainStatement):
                lineas = self.statement_executor.execute(ast)
                return Resultado(columnas=["QUERY PLAN"], filas=[(linea,) for linea in lineas],
                                 plan=lineas)

            # --- SELECT ---
            if isinstance(ast, SelectStatement):
                plan = self.sql_executor.planner.plan(ast)
                # Pasa por el StatementExecutor para tomar locks S y respetar
                # la transacción activa de la sesión.
                filas_dict = self.statement_executor.select(plan)

                if filas_dict:
                    columnas = list(filas_dict[0].keys())
                    filas = [tuple(d.get(c) for c in columnas) for d in filas_dict]
                else:
                    columnas = self._columnas_del_plan(plan)
                    filas = []
                return Resultado(columnas=columnas, filas=filas)

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
        existentes = [ruta for ruta in self._archivos_tabla(statement.name) if os.path.exists(ruta)]
        if existentes:
            raise ValueError(f"Ya existe el archivo de la tabla {statement.name!r}: {existentes[0]}")
        indexes = None
        primary_key = statement.primary_key
        # SEQUENTIAL y BTREE se ordenan por la clave primaria (o por la primera columna).
        key_field = primary_key or fields[0]
        constraint = f"{statement.name}_pkey"
        if statement.storage_method == "sequential":
            storage = SequentialFile(
                f"{path}.main", f"{path}.aux", schema, key_field=key_field
            )
        elif statement.storage_method == "btree":
            # B+ agrupado: los registros viven en las hojas ordenados por la clave,
            # que es única y queda registrada como índice agrupado.
            storage = ClusteredBPlusFile(os.path.join(DEMO_DIR, f"{statement.name}.bpt"), schema,
                                         key_field=key_field)
            indexes = {key_field: storage.primary_index_info(constraint)}
            primary_key = key_field
        else:
            storage = HeapFile(path, schema)
            if primary_key is not None:
                # Índice implícito de la clave primaria, como en PostgreSQL.
                index = ExtendibleHash()
                indexes = {primary_key: IndexInfo(constraint, primary_key, index)}
        try:
            self.catalog.register_table(statement.name, storage, indexes, primary_key=primary_key)
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
        index_file = f"{index_path}.hash" if statement.method == "hash" else f"{index_path}.bpt"
        if os.path.exists(index_file):
            raise ValueError(f"Ya existe el archivo {index_file!r}; usa otro nombre de índice")
        if statement.method == "hash":
            index = ExtendibleHash(filepath=index_file)
            metadata = IndexInfo(statement.name, statement.column, index)
        else:
            key_size = binding.storage.schema.sizes[position]
            # Nodos que llenan una página de 4 KB (M = 254 para claves enteras).
            order = (4096 - NODE_HEADER_SIZE - CHILD_SIZE) // (CHILD_SIZE + key_size)
            index = BPlusTreeUnclustered(
                index_file, key_type=key_type, order=order, key_size=key_size
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
        """Cierra índices y storages (necesario en Windows antes de borrar archivos).

        Es idempotente. Intenta cerrar todo y reporta el primer error al final.
        """
        if self._cerrado:
            return
        self._cerrado = True
        errores = []
        for binding in self.catalog.tables.values():
            for registro in binding.indexes.values():
                try:
                    if hasattr(registro.index, "close"):
                        registro.index.close()
                except Exception as exc:
                    errores.append(exc)
            try:
                if hasattr(binding.storage, "close"):
                    binding.storage.close()
            except Exception as exc:
                errores.append(exc)
        if errores:
            raise RuntimeError(f"Error al cerrar el motor: {errores[0]}") from errores[0]
