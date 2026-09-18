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
    DeleteStatement,
    InsertStatement,
    SelectStatement,
    TransactionStatement,
)
from engine.query.catalog import Catalog
from engine.query.sql_executor import SQLExecutor
from engine.query.statement_executor import StatementExecutor
from engine.query.parser import parse_script
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

    def _cargar_tablas_demo(self):
        """Crea tablas de ejemplo para la demo."""
        os.makedirs(DEMO_DIR, exist_ok=True)

        # --- Tabla cuentas ---
        path_cuentas = os.path.join(DEMO_DIR, "cuentas.db")
        if os.path.exists(path_cuentas):
            os.remove(path_cuentas)

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
        if os.path.exists(path_productos):
            os.remove(path_productos)

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

        # Si hay varios mensajes, los concatenamos
        if mensajes:
            ultimo_resultado.mensaje = "\n".join(mensajes)
            # Si la ultima sentencia dio tabla, conservamos el mensaje aparte
            if ultimo_resultado.tiene_tabla:
                # El mensaje no se muestra cuando hay tabla, pero lo dejamos por si acaso
                pass

        return ultimo_resultado

    def _ejecutar_una(self, ast) -> Resultado:
        """Ejecuta una sola sentencia AST."""
        try:
            # --- Transacciones ---
            if isinstance(ast, TransactionStatement):
                mensaje = self.statement_executor.execute(ast)
                return Resultado(mensaje=mensaje)

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

                return Resultado(columnas=columnas, filas=filas, plan=plan)

            return Resultado(error=f"Sentencia no soportada: {type(ast).__name__}")

        except Exception as e:
            return Resultado(error=str(e))

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