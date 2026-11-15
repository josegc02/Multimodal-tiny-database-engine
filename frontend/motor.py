"""Encapsula el motor de base de datos para el frontend.

Modo demo (por defecto, el de la interfaz Tkinter): cada vez que se crea un
Motor se vacía DEMO_DIR (solo los archivos que genera el motor) y se crean las
tablas de ejemplo; nada sobrevive al cierre de la aplicación. Con
modo_demo=False (la API) no se borra ni se crea nada; la capa de almacenamiento
permite reabrir sus archivos (ver los tests de reapertura de HeapFile,
SequentialFile y B+).

Une:
- Catalog con tablas de demo
- LockManager + TransactionManager
- SQLExecutor (planes y algoritmos de consulta)
- StatementExecutor (SELECT/INSERT/DELETE/BEGIN/COMMIT con locks)
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil

from engine.concurrency.lock_manager import LockManager
from engine.concurrency.transaction_manager import TransactionManager
from engine.query.ast import (
    ColumnDefinition,
    CopyStatement,
    CreateIndexStatement,
    CreateTableStatement,
    DeleteStatement,
    ExplainStatement,
    ForeignKeyDefinition,
    InsertStatement,
    SelectStatement,
    TransactionStatement,
)
from engine.query.catalog import Catalog, ForeignKey
from engine.query.planner import IndexInfo
from engine.query.sql_executor import SQLExecutor
from engine.query.statement_executor import StatementExecutor
from engine.query.parser import parse_script
from frontend import mapa_datos
from engine.indexes import ExtendibleHash
from engine.indexes.rtree import RTree
from engine.indexes.spimi import SpimiIndex
from engine.indexes.vector_index import VectorIndex
from engine.indexes.bplus_tree import CHILD_SIZE, NODE_HEADER_SIZE
from engine.indexes.bplus_tree_unclustered import BPlusTreeUnclustered
from engine.storage.clustered_file import ClusteredBPlusFile
from engine.storage.media_store import MediaStore
from engine.storage.text_store import TextStore
from engine.storage.heap_file import HeapFile
from engine.storage.sequential_file import SequentialFile
from engine.spatial.geometry import Point


# Raíz del proyecto: base de las rutas relativas de COPY.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Carpeta de trabajo del modo demo (relativa a la raíz del proyecto, no al cwd).
DEMO_DIR = os.path.join(PROJECT_DIR, "demo_data")

TIPOS_MULTIMEDIA = ("image", "audio")

# Archivos que genera el motor y que el modo demo elimina al iniciar.
_EXTENSIONES_MOTOR = (".db", ".main", ".aux", ".bpt", ".hash", ".idx", ".rtree", ".reorg", ".tmp", ".text", ".spimi", ".delta", ".media", ".hnsw", ".ivf")
_DIRECTORIOS_TEMPORALES = (".bplus-build-",)

# Fuera del modo demo, las tablas e índices creados se guardan aquí (en el
# directorio del Motor) para reabrirlos al iniciar.
ARCHIVO_CATALOGO = "catalogo.json"
VERSION_CATALOGO = 1


def _ddl_a_dict(statement) -> dict:
    """CREATE TABLE / CREATE INDEX como diccionario serializable en JSON."""
    tipo = "tabla" if isinstance(statement, CreateTableStatement) else "indice"
    return {"tipo": tipo, **dataclasses.asdict(statement)}


def _ddl_desde_dict(datos: dict):
    """Inverso de _ddl_a_dict."""
    datos = dict(datos)
    tipo = datos.pop("tipo")
    if tipo == "indice":
        return CreateIndexStatement(**datos)
    if tipo != "tabla":
        raise ValueError(f"Entrada de catálogo desconocida: {tipo!r}")
    datos["columns"] = tuple(ColumnDefinition(**c) for c in datos["columns"])
    datos["foreign_keys"] = tuple(ForeignKeyDefinition(**f) for f in datos["foreign_keys"])
    return CreateTableStatement(**datos)


def _valor_json(valor):
    """Convierte un valor de una fila a un tipo que acepta json.dumps."""
    if valor is None or isinstance(valor, (bool, int, float, str)):
        return valor
    if isinstance(valor, Point):
        return {"lat": valor.lat, "lon": valor.lon}
    if hasattr(valor, "tolist"):  # escalares y arreglos de numpy
        return valor.tolist()
    return str(valor)


class Resultado:
    """Resultado de una ejecucion SQL.

    Alguno de estos campos estara lleno:
    - columnas + filas: para SELECT y EXPLAIN (columna "QUERY PLAN")
    - mensaje: para INSERT/DELETE/COPY/BEGIN/COMMIT
    - error: si algo fallo
    - plan: líneas del QUERY PLAN (solo con EXPLAIN / EXPLAIN ANALYZE)
    """

    def __init__(self, columnas=None, filas=None, mensaje=None,
                 plan=None, error=None, plan_nodos=None, tiempos=(None, None), mapa=None):
        self.columnas = columnas or []
        self.filas = filas or []
        self.mensaje = mensaje
        self.plan = plan
        self.plan_nodos = plan_nodos  # árbol del plan como datos (panel de análisis)
        self.tiempos = tiempos        # (planificación, ejecución) en segundos, con ANALYZE
        self.error = error
        self.mapa = mapa

    def a_dict(self) -> dict:
        """El resultado como diccionario serializable en JSON (para la API).

        POINT pasa a {"lat", "lon"} y los escalares de numpy (puntajes de
        SIMILARITY_SCORE, por ejemplo) a números de Python.
        """
        planificacion, ejecucion = self.tiempos
        return {
            "columnas": list(self.columnas),
            "filas": [[_valor_json(valor) for valor in fila] for fila in self.filas],
            "mensaje": self.mensaje,
            "plan": list(self.plan) if self.plan is not None else None,
            "tiempos": {"planificacion": planificacion, "ejecucion": ejecucion},
            "error": self.error,
        }

    @property
    def tiene_tabla(self):
        return bool(self.columnas)

    @property
    def tiene_error(self):
        return self.error is not None


class Motor:
    """Fachada del motor para el frontend."""

    def __init__(self, directorio: str | None = None, modo_demo: bool = True):
        """Crea el motor sobre `directorio` (por defecto DEMO_DIR).

        Con `modo_demo=True` (la interfaz Tkinter) vacía la carpeta y crea las
        tablas de ejemplo. Con `modo_demo=False` (la API) no borra ni crea nada.
        """
        # Se resuelve al crear el Motor (no al importar) para que DEMO_DIR pueda cambiarse.
        self.directorio = os.path.abspath(directorio or DEMO_DIR)
        self.modo_demo = modo_demo
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
        self._puntos_mapa = {}  # tabla -> puntos para el mapa
        if modo_demo:
            self._limpiar_directorio_demo()
            self._cargar_tablas_demo()
        else:
            os.makedirs(self.directorio, exist_ok=True)
            self._reabrir_catalogo()

    # ------------------------------------------------------------------
    # Carga de tablas de demo
    # ------------------------------------------------------------------

    def _limpiar_directorio_demo(self):
        """Elimina los archivos de sesiones anteriores.

        No ignora errores: en Windows un archivo abierto por otra instancia no
        se puede borrar, y continuar reabriría datos viejos sin avisar.
        """
        os.makedirs(self.directorio, exist_ok=True)
        errores = []
        for nombre in os.listdir(self.directorio):
            ruta = os.path.join(self.directorio, nombre)
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
            storage = HeapFile(os.path.join(self.directorio, f"{nombre}.db"), schema)
            campos = [campo[0] for campo in schema]
            for fila in filas:
                storage.insert(dict(zip(campos, fila)))
            self.catalog.register_table(nombre, storage)

    # ------------------------------------------------------------------
    # Ejecucion
    # ------------------------------------------------------------------

    def _archivos_tabla(self, nombre):
        """Archivos que usaría una tabla según su método de almacenamiento."""
        base = os.path.join(self.directorio, nombre)
        return (f"{base}.db", f"{base}.db.main", f"{base}.db.aux", f"{base}.bpt", f"{base}.text", f"{base}.media")

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
        if not isinstance(ast, SelectStatement):
            self._puntos_mapa.clear()  # pudo cambiar datos: el mapa relee la tabla
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
                                 plan=lineas, plan_nodos=getattr(lineas, "nodes", None),
                                 tiempos=(getattr(lineas, "planning", None), getattr(lineas, "execution", None)))

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
                return Resultado(columnas=columnas, filas=filas, mapa=self._mapa(ast, filas_dict))

            return Resultado(error=f"Sentencia no soportada: {type(ast).__name__}")

        except Exception as e:
            return Resultado(error=str(e))

    def _mapa(self, statement, rows):
        """Puntos de la tabla (cacheados), ids del resultado y figuras de la consulta.

        Los puntos se leen una vez por tabla; cualquier sentencia que pueda
        escribir vacía la caché. Así el mapa no agrega un scan a cada SELECT.
        """
        binding = self.catalog.table(statement.from_table.name)
        columna = mapa_datos.columna_punto(binding)
        if columna is None:
            return None
        nombre = statement.from_table.name
        if nombre not in self._puntos_mapa:
            self._puntos_mapa[nombre] = mapa_datos.puntos_de_tabla(binding, columna)
        circle, polygon = mapa_datos.figuras(statement.where)
        return {"table": nombre,
                "points": self._puntos_mapa[nombre],
                "result_ids": mapa_datos.ids_resultado(rows, mapa_datos.identificador(binding)),
                "circle": circle or mapa_datos.centro_knn(statement),
                "polygon": polygon}

    def _crear_tabla(self, statement: CreateTableStatement, *, reabrir: bool = False) -> str:
        """Crea la tabla y la incorpora al catálogo de la sesión.

        Con `reabrir=True` abre los archivos que ya existen (de una sesión
        anterior) en vez de exigir que no existan, y no vuelve a guardarla en
        el catálogo en disco.
        """
        if statement.name in self.catalog.tables:
            raise ValueError(f"La tabla {statement.name!r} ya existe")
        fields = [column.name for column in statement.columns]
        if len(fields) != len(set(fields)):
            raise ValueError("La tabla contiene columnas repetidas")
        schema = []
        textos = TextStore(os.path.join(self.directorio, f"{statement.name}.text"))
        multimedia = None
        for column in statement.columns:
            definition = (column.name, column.type)
            if column.type == "str":
                definition += (column.size,)
            elif column.type == "text":
                definition += (textos,)
            elif column.type in TIPOS_MULTIMEDIA:
                # Se crea solo si hay columnas multimedia; el archivo aparece con el primer INSERT.
                if multimedia is None:
                    multimedia = MediaStore(os.path.join(self.directorio, f"{statement.name}.media"))
                definition += (multimedia,)
            schema.append(definition)

        path = os.path.join(self.directorio, f"{statement.name}.db")
        existentes = [ruta for ruta in self._archivos_tabla(statement.name) if os.path.exists(ruta)]
        if existentes and not reabrir:
            raise ValueError(f"Ya existe el archivo de la tabla {statement.name!r}: {existentes[0]}")
        indexes = None
        primary_key = statement.primary_key
        # SEQUENTIAL y BTREE se ordenan por la clave primaria (o por la primera columna).
        key_field = primary_key or fields[0]
        kinds = {column.name: column.type for column in statement.columns}
        if kinds[key_field] == "point" and (primary_key or statement.storage_method != "heap"):
            raise ValueError("POINT no puede ser clave primaria ni clave de orden físico; usa una columna INT")
        if kinds[key_field] == "text" and (primary_key or statement.storage_method != "heap"):
            raise ValueError("TEXT no puede ser clave primaria ni clave de orden físico; usa una columna INT")
        if kinds[key_field] in TIPOS_MULTIMEDIA and (primary_key or statement.storage_method != "heap"):
            raise ValueError(f"{kinds[key_field].upper()} no puede ser clave primaria ni clave de orden físico; "
                             "usa una columna INT")
        constraint = f"{statement.name}_pkey"
        if statement.storage_method == "sequential":
            storage = SequentialFile(
                f"{path}.main", f"{path}.aux", schema, key_field=key_field
            )
            # La clave de ordenamiento queda como índice: búsqueda binaria del archivo.
            nombre_clave = constraint if primary_key else f"{statement.name}_{key_field}_seq"
            indexes = {key_field: storage.primary_index_info(nombre_clave)}
        elif statement.storage_method == "btree":
            # B+ agrupado: los registros viven en las hojas ordenados por la clave,
            # que es única y queda registrada como índice agrupado.
            storage = ClusteredBPlusFile(os.path.join(self.directorio, f"{statement.name}.bpt"), schema,
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
        try:
            self._registrar_llaves_foraneas(statement)
        except Exception:
            # La tabla no queda a medias: se quita del catálogo y se borran sus
            # archivos (nunca al reabrir: serían los datos de la sesión anterior).
            del self.catalog.tables[statement.name]
            storage.close()
            if not reabrir:
                for ruta in self._archivos_tabla(statement.name):
                    if os.path.exists(ruta):
                        os.remove(ruta)
            raise
        if not reabrir:
            self._guardar_en_catalogo(statement)
        return f"Tabla {statement.name} creada"

    def _registrar_llaves_foraneas(self, statement: CreateTableStatement) -> None:
        """Registra cada REFERENCES y crea un índice sobre la columna hija.

        El índice (como recomienda PostgreSQL) evita recorrer la tabla hija en
        cada DELETE del padre para aplicar RESTRICT o CASCADE.
        """
        for definition in statement.foreign_keys:
            column = next(c for c in statement.columns if c.name == definition.column)
            if column.type == "point":
                raise ValueError("POINT no admite llaves foráneas")
            if column.type == "text":
                raise ValueError("TEXT no admite llaves foráneas")
            if column.type in TIPOS_MULTIMEDIA:
                raise ValueError(f"{column.type.upper()} no admite llaves foráneas")
            padre = self.catalog.table(definition.ref_table)
            columna_padre = definition.ref_column or padre.primary_key
            if columna_padre is None:
                raise ValueError(f"La tabla {definition.ref_table!r} no tiene clave primaria para referenciar")
            nombre = f"{statement.name}_{definition.column}_fkey"
            self.catalog.add_foreign_key(ForeignKey(
                nombre, statement.name, definition.column, definition.ref_table,
                columna_padre, definition.on_delete))
            if definition.column not in self.catalog.table(statement.name).indexes:
                indice = ExtendibleHash()
                self.catalog.register_index(statement.name, definition.column, indice,
                                            IndexInfo(f"{nombre}_idx", definition.column, indice))

    def _crear_indice(self, statement: CreateIndexStatement, *, reabrir: bool = False) -> str:
        """Crea, carga y registra un índice SQL sobre una tabla.

        Con `reabrir=True` acepta que su archivo exista; el catálogo lo
        reconstruye igual desde la tabla al registrarlo.
        """
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
        if (statement.method == "rtree") != (key_type == "point"):
            raise ValueError("RTREE requiere una columna POINT; POINT solo admite índices RTREE")
        if statement.method == "spimi" and key_type not in ("str", "text"):
            raise ValueError("SPIMI requiere una columna TEXT o VARCHAR")
        if key_type == "text" and statement.method != "spimi":
            raise ValueError("TEXT solo admite índices SPIMI")
        if (statement.method in ("hnsw", "ivf")) != (key_type in TIPOS_MULTIMEDIA):
            raise ValueError("HNSW e IVF requieren una columna IMAGE o AUDIO; IMAGE y AUDIO solo admiten índices HNSW o IVF")
        index_path = os.path.join(self.directorio, f"{statement.table}_{statement.name}")
        extension = {"hash": "hash", "btree": "bpt", "rtree": "rtree", "spimi": "spimi",
                     "hnsw": "hnsw", "ivf": "ivf"}[statement.method]
        index_file = f"{index_path}.{extension}"
        if os.path.exists(index_file) and not reabrir:
            raise ValueError(f"Ya existe el archivo {index_file!r}; usa otro nombre de índice")
        if statement.method == "rtree":
            index = RTree(index_file)
            metadata = IndexInfo(statement.name, statement.column, index, spatial=True)
        elif statement.method == "spimi":
            index = SpimiIndex(index_file, statement.language)
            metadata = IndexInfo(statement.name, statement.column, index, text=True)
        elif statement.method in ("hnsw", "ivf"):
            index = VectorIndex(index_file, statement.method, statement.metric or "euclidean")
            metadata = IndexInfo(statement.name, statement.column, index, vector=True)
        elif statement.method == "hash":
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
        if not reabrir:
            self._guardar_en_catalogo(statement)
        return f"Índice {statement.name} creado sobre {statement.table}.{statement.column}"

    # ------------------------------------------------------------------
    # Catálogo en disco (solo fuera del modo demo)
    # ------------------------------------------------------------------

    @property
    def ruta_catalogo(self) -> str:
        return os.path.join(self.directorio, ARCHIVO_CATALOGO)

    def _leer_catalogo(self) -> list:
        if not os.path.exists(self.ruta_catalogo):
            return []
        with open(self.ruta_catalogo, encoding="utf-8") as fh:
            datos = json.load(fh)
        if datos.get("version") != VERSION_CATALOGO:
            raise RuntimeError(f"Versión de catálogo no soportada en {self.ruta_catalogo}: {datos.get('version')!r}")
        return datos["ddl"]

    def _reabrir_catalogo(self) -> None:
        """Reabre, en el orden en que se crearon, las tablas e índices guardados.

        Los índices se reconstruyen desde las tablas al registrarse; los
        vectores de IMAGE/AUDIO se leen de <tabla>.media sin volver a extraerlos.
        Si algo falla, se cierra lo ya abierto y se informa qué entrada falló.
        """
        for datos in self._leer_catalogo():
            statement = _ddl_desde_dict(datos)
            try:
                if isinstance(statement, CreateTableStatement):
                    self._crear_tabla(statement, reabrir=True)
                else:
                    self._crear_indice(statement, reabrir=True)
            except Exception as exc:
                self.cerrar()
                raise RuntimeError(
                    f"No se pudo reabrir {datos['tipo']} {statement.name!r} de {self.ruta_catalogo}: {exc}"
                ) from exc

    def _guardar_en_catalogo(self, statement) -> None:
        """Agrega un CREATE TABLE / CREATE INDEX exitoso al catálogo en disco.

        Se escribe en un archivo temporal y se reemplaza de forma atómica, para
        que un corte nunca deje el catálogo a medias.
        """
        if self.modo_demo:
            return
        ddl = self._leer_catalogo() + [_ddl_a_dict(statement)]
        temporal = self.ruta_catalogo + ".tmp"
        with open(temporal, "w", encoding="utf-8") as fh:
            json.dump({"version": VERSION_CATALOGO, "ddl": ddl}, fh, ensure_ascii=False, indent=2)
        os.replace(temporal, self.ruta_catalogo)

    def _columnas_del_plan(self, plan):
        """Intenta extraer los nombres de columna del plan (para SELECT vacio)."""
        try:
            while plan.operation != "Project" and len(plan.children) == 1:
                plan = plan.children[0]
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
                for textos in binding.storage.schema.text_stores.values():
                    textos.close()
                for multimedia in set(binding.storage.schema.media_stores.values()):
                    multimedia.close()
            except Exception as exc:
                errores.append(exc)
        if errores:
            raise RuntimeError(f"Error al cerrar el motor: {errores[0]}") from errores[0]
