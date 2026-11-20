"""API REST del motor de base de datos (Parte 5).

Levantar desde la raíz del proyecto:

    uvicorn api.main:app --reload

Variables de entorno (opcionales):
- BD2_DATA_DIR: carpeta de las tablas e índices (por defecto data/app).
- BD2_ARCHIVOS: carpetas, separadas por os.pathsep, desde las que GET /archivos
  puede servir imágenes y audios (por defecto datasets, fotos y BD2_DATA_DIR).
- BD2_CORS_ORIGINS: orígenes del front web, separados por comas
  (por defecto http://localhost:5173 y http://127.0.0.1:5173).
- BD2_LLM: LLM de POST /asistente/preguntar: gemini (por defecto), claude o ninguno.
- GEMINI_API_KEY / ANTHROPIC_API_KEY: la key del proveedor elegido.
- BD2_LLM_MODELO: cambia el modelo (por defecto gemini-flash-lite-latest o claude-haiku-5-5).
- BD2_PALABRAS_CLAVE=local: palabras clave con el glosario y una sola llamada al LLM.
- BD2_SIN_LLM=1: el asistente solo devuelve fragmentos (demo sin internet).

El motor guarda una sola sesión SQL, así que la API atiende una petición a la
vez y cada petición es autocommit: si un script deja una transacción abierta,
se deshace y se responde con error.
"""

from __future__ import annotations

import os
import threading
import time
import csv
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from api.asistente import (ErrorAsistente, ErrorLLM, crear_llm, indexar_pdf, listar_documentos,
                           obtener_documento, preguntar)
from api.tienda import precalentar, rutas_tienda

from engine.indexes.extendible_hash import ExtendibleHash
from engine.indexes.bplus_tree_unclustered import BPlusTreeUnclustered
from engine.indexes.rtree import RTree
from engine.indexes.spimi import SpimiIndex
from engine.indexes.vector_index import VectorIndex
from engine.storage.clustered_file import ClusteredBPlusFile, PrimaryClusteredIndex
from engine.storage.sequential_file import SequentialFile, SequentialKeyIndex
from frontend.motor import PROJECT_DIR, Motor
from rag.arxiv import DATASET_DIR, nombre_pdf
from rag.chunking import extraer_paginas

DATA_DIR_DEFECTO = os.path.join(PROJECT_DIR, "data", "app")
ORIGENES_DEFECTO = ("http://localhost:5173", "http://127.0.0.1:5173")
EXTENSIONES_ARCHIVOS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
                        ".wav", ".mp3", ".ogg", ".flac")
TIPOS_SQL = {"int": "INT", "float": "FLOAT", "str": "VARCHAR", "point": "POINT",
             "text": "TEXT", "image": "IMAGE", "audio": "AUDIO"}


MAX_PDF = 20 * 1024 * 1024


def _ruta_pdf(documento: dict, carpeta: Path) -> Path | None:
    """Dónde está el PDF de un documento: arXiv, clase del curso o subido desde la web."""
    if documento.get("arxiv_id"):
        return carpeta / "pdf" / nombre_pdf(documento["arxiv_id"])
    if documento.get("fuente") == "curso":
        subido = carpeta / "subidos" / f"{documento['id']}.pdf"
        if subido.is_file():
            return subido
        manifiesto = carpeta / "curso" / "curso.csv"
        if manifiesto.is_file():
            with manifiesto.open(encoding="utf-8", newline="") as stream:
                for fila in csv.DictReader(stream):
                    if fila.get("titulo") == documento.get("titulo"):
                        return carpeta / "curso" / fila["archivo"]
        return None
    return carpeta / "subidos" / f"{documento['id']}.pdf"


class ConsultaSQL(BaseModel):
    sql: str


class Pregunta(BaseModel):
    pregunta: str = Field(min_length=1, max_length=1000)
    k: int = Field(5, ge=1, le=20, description="Cuántos fragmentos recuperar")
    usar_llm: bool = Field(True, description="false: solo los fragmentos, sin redactar respuesta")


_LLM_DESDE_ENTORNO = object()


def _error(estado: int, mensaje: str) -> JSONResponse:
    return JSONResponse(status_code=estado, content={"error": mensaje})


def _almacenamiento(storage) -> str:
    if isinstance(storage, ClusteredBPlusFile):
        return "btree"
    if isinstance(storage, SequentialFile):
        return "sequential"
    return "heap"


def _metodo_indice(registro) -> str:
    index = registro.index
    if isinstance(index, VectorIndex):
        return index.method
    for clase, nombre in ((SpimiIndex, "spimi"), (RTree, "rtree"), (ExtendibleHash, "hash"),
                          (BPlusTreeUnclustered, "btree"),
                          # Clave de orden físico de las tablas BTREE y SEQUENTIAL.
                          (PrimaryClusteredIndex, "btree agrupado"), (SequentialKeyIndex, "secuencial")):
        if isinstance(index, clase):
            return nombre
    return type(index).__name__


def _columnas(schema) -> list[dict]:
    columnas = []
    for nombre, tipo, tamano in zip(schema.fields, schema.types, schema.sizes):
        sql = TIPOS_SQL.get(tipo, tipo.upper())
        columnas.append({"nombre": nombre, "tipo": f"{sql}({tamano})" if tipo == "str" else sql})
    return columnas


def _carpetas(texto: str | None, defecto: list[str]) -> list[str]:
    carpetas = [c for c in (texto or "").split(os.pathsep) if c] or defecto
    return [os.path.realpath(os.path.join(PROJECT_DIR, c)) for c in carpetas]


def _dentro_de(ruta: str, carpeta: str) -> bool:
    try:
        return os.path.commonpath([ruta, carpeta]) == carpeta
    except ValueError:  # otra unidad de disco en Windows
        return False


def _llm_desde_entorno():
    if os.environ.get("BD2_SIN_LLM", "").strip().lower() in ("1", "true", "si", "sí", "yes"):
        return None
    return crear_llm()


def create_app(directorio: str | None = None, carpetas_archivos: list[str] | None = None,
               origenes: list[str] | None = None, llm=_LLM_DESDE_ENTORNO,
               carpeta_papers: str | None = None) -> FastAPI:
    """Crea la aplicación. Los argumentos tienen prioridad sobre las variables de entorno.

    ``llm`` es el modelo del asistente (cualquier objeto con ``completar``);
    ``None`` lo apaga. Por defecto sale de BD2_LLM (Gemini), salvo con BD2_SIN_LLM=1.
    """
    palabras = os.environ.get("BD2_PALABRAS_CLAVE", "llm").strip().lower()
    estado: dict = {"llm": _llm_desde_entorno() if llm is _LLM_DESDE_ENTORNO else llm,
                    "palabras_con_llm": palabras != "local"}
    lock = threading.Lock()
    subida = threading.Lock()
    estado["papers"] = Path(carpeta_papers or os.environ.get("BD2_PAPERS_DIR") or DATASET_DIR)

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        datos = os.path.abspath(directorio or os.environ.get("BD2_DATA_DIR") or DATA_DIR_DEFECTO)
        estado["motor"] = Motor(directorio=datos, modo_demo=False)
        precalentar(estado, lock)
        estado["archivos"] = (
            [os.path.realpath(c) for c in carpetas_archivos] if carpetas_archivos is not None
            else _carpetas(os.environ.get("BD2_ARCHIVOS"), ["datasets", "fotos", datos]))
        try:
            yield
        finally:
            estado.pop("motor").cerrar()

    app = FastAPI(title="Minigestor BD2", version="1.0", lifespan=ciclo_de_vida)
    if origenes is None:
        texto = os.environ.get("BD2_CORS_ORIGINS")
        origenes = [o.strip() for o in texto.split(",") if o.strip()] if texto else list(ORIGENES_DEFECTO)
    app.add_middleware(CORSMiddleware, allow_origins=origenes, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"])

    @app.get("/salud")
    def salud():
        """Comprueba que la API y el motor están vivos."""
        with lock:
            return {"ok": True, "tablas": len(estado["motor"].catalog.tables)}

    @app.post("/sql")
    def ejecutar_sql(consulta: ConsultaSQL):
        """Ejecuta una o varias sentencias SQL separadas por ';'.

        Responde con el resultado de la última. Cada petición es autocommit:
        una transacción que quede abierta se deshace y se informa como error.
        """
        motor = estado["motor"]
        with lock:
            resultado = motor.ejecutar(consulta.sql)
            sesion = motor.statement_executor
            if sesion.in_transaction:
                motor.ejecutar("ROLLBACK")
                if not resultado.tiene_error:
                    return _error(400, "La transacción quedó abierta y se deshizo: "
                                       "termina el script con COMMIT o ROLLBACK")
            if resultado.tiene_error:
                return _error(400, resultado.error)
            datos = resultado.a_dict()
            del datos["error"]
            return datos

    @app.get("/tablas")
    def tablas():
        """Tablas con su almacenamiento, columnas, clave primaria e índices."""
        with lock:
            respuesta = []
            for nombre, binding in sorted(estado["motor"].catalog.tables.items()):
                respuesta.append({
                    "nombre": nombre,
                    "almacenamiento": _almacenamiento(binding.storage),
                    "filas_estimadas": binding.statistics.rows if binding.statistics else None,
                    "clave_primaria": binding.primary_key,
                    "columnas": _columnas(binding.storage.schema),
                    "indices": [{"nombre": registro.metadata.name if registro.metadata else columna,
                                 "columna": columna, "metodo": _metodo_indice(registro)}
                                for columna, registro in binding.indexes.items()],
                })
            return respuesta

    @app.get("/archivos")
    def archivos(ruta: str = Query(..., description="Ruta guardada en una columna IMAGE o AUDIO")):
        """Sirve una imagen o audio, solo desde las carpetas permitidas."""
        real = os.path.realpath(ruta if os.path.isabs(ruta) else os.path.join(os.getcwd(), ruta))
        permitida = any(_dentro_de(real, carpeta) for carpeta in estado["archivos"])
        if not permitida or not real.lower().endswith(EXTENSIONES_ARCHIVOS):
            return _error(403, "Archivo fuera de las carpetas permitidas o con un tipo no admitido")
        if not os.path.isfile(real):
            return _error(404, f"No existe el archivo: {ruta}")
        return FileResponse(real)

    def _sql_con_lock(sql: str):
        with lock:
            return estado["motor"].ejecutar(sql)

    @app.post("/asistente/preguntar")
    def asistente_preguntar(cuerpo: Pregunta):
        """Responde con los papers: palabras clave en inglés, BM25 y LLM con citas [n].

        Solo las consultas SQL toman el lock; la llamada al LLM no bloquea al resto.
        """
        llm = estado["llm"] if cuerpo.usar_llm else None
        try:
            return preguntar(_sql_con_lock, cuerpo.pregunta, cuerpo.k, llm,
                             palabras_con_llm=estado["palabras_con_llm"])
        except ErrorAsistente as exc:
            return _error(400, str(exc))
        except ErrorLLM as exc:
            return _error(502, str(exc))

    @app.get("/asistente/estado")
    def asistente_estado():
        """Qué hay cargado y con qué LLM se responde (la barra lateral del front)."""
        llm = estado["llm"]
        conteos = {}
        for tabla in ("papers", "fragmentos"):
            resultado = _sql_con_lock(f"SELECT COUNT(*) AS n FROM {tabla}")
            conteos[tabla] = None if resultado.tiene_error else resultado.filas[0][0]
        return {"corpus": conteos["fragmentos"] is not None, "documentos": conteos["papers"],
                "fragmentos": conteos["fragmentos"], "llm": getattr(llm, "modelo", None) if llm else None,
                "palabras_con_llm": estado["palabras_con_llm"]}

    @app.get("/asistente/documentos")
    def asistente_documentos():
        """La biblioteca: papers y clases con su número de fragmentos."""
        try:
            return listar_documentos(_sql_con_lock)
        except ErrorAsistente as exc:
            return _error(400, str(exc))

    @app.get("/asistente/documentos/{paper_id}")
    def asistente_documento(paper_id: int):
        """Un documento con su abstract y sus fragmentos en orden."""
        try:
            documento = obtener_documento(_sql_con_lock, paper_id)
        except ErrorAsistente as exc:
            return _error(400, str(exc))
        if documento is None:
            return _error(404, f"No existe el documento {paper_id}")
        return documento

    @app.get("/asistente/documentos/{paper_id}/pdf")
    def asistente_pdf(paper_id: int):
        """El PDF del documento, si está en esta máquina (no se versiona por licencia).

        El front lo abre en una página con ``#page=N``.
        """
        try:
            filas = _sql_con_lock(f"SELECT id, arxiv_id, titulo, fuente FROM papers WHERE id = {paper_id}")
        except ErrorAsistente as exc:
            return _error(400, str(exc))
        if filas.tiene_error or not filas.filas:
            return _error(404, f"No existe el documento {paper_id}")
        ruta = _ruta_pdf(dict(zip(filas.columnas, filas.filas[0])), estado["papers"])
        if ruta is None or not ruta.is_file():
            return _error(404, "El PDF no está en esta máquina: descárguelo con 'python -m rag.arxiv descargar'")
        return FileResponse(ruta, media_type="application/pdf")

    @app.post("/asistente/documentos")
    def asistente_subir(archivo: UploadFile = File(...), titulo: str = Form(...), autores: str = Form(""),
                        anio: int = Form(...), tipo: str = Form("paper")):
        """Sube un PDF: extrae el texto por página, lo fragmenta y lo inserta (SPIMI incluido)."""
        datos = archivo.file.read(MAX_PDF + 1)
        if len(datos) > MAX_PDF:
            return _error(413, "El PDF pasa de 20 MB")
        if not datos.startswith(b"%PDF-"):
            return _error(400, "El archivo no es un PDF")
        if tipo not in ("paper", "clase"):
            return _error(400, "tipo debe ser 'paper' o 'clase'")
        carpeta = estado["papers"] / "subidos"
        carpeta.mkdir(parents=True, exist_ok=True)
        with subida:  # una subida a la vez: los ids nuevos salen de MAX(id)
            temporal = carpeta / "subiendo.pdf"
            temporal.write_bytes(datos)
            try:
                t = time.perf_counter()
                paginas = extraer_paginas(temporal)
                ms_extraccion = round((time.perf_counter() - t) * 1000, 1)
                fuente = "curso" if tipo == "clase" else "subido"
                resultado = indexar_pdf(_sql_con_lock, paginas, titulo, autores, anio, fuente, fuente)
            except ErrorAsistente as exc:
                temporal.unlink(missing_ok=True)
                return _error(400, str(exc))
            except Exception as exc:  # PDF corrupto o cifrado
                temporal.unlink(missing_ok=True)
                return _error(400, f"No se pudo leer el PDF: {exc}")
            temporal.replace(carpeta / f"{resultado['id']}.pdf")
        return {**resultado, "ms_extraccion": ms_extraccion}

    app.include_router(rutas_tienda(estado, lock))
    return app


app = create_app()
