"""Selección y descarga de papers de arXiv (issue #97).

Dos pasos, para que el corpus sea reproducible aunque arXiv cambie el
orden de sus resultados con el tiempo:

1. ``seleccionar`` consulta la API de arXiv con temas fijos y escribe
   ``datasets/papers/seleccion.csv`` con la metadata (título, autores, año,
   abstract, categoría), la **versión** exacta del PDF y su licencia.
   Ese CSV es la lista congelada: se versiona en Git.
2. ``descargar`` baja los PDFs de esa lista a ``datasets/papers/pdf/``
   (ignorado por Git) y verifica que existan y sean PDF.

Uso, desde la raíz del repositorio::

    python -m rag.arxiv seleccionar --maximo 250
    python -m rag.arxiv descargar

Se respeta la política de la API: una petición cada 3 segundos y un
User-Agent identificable. Solo usa la biblioteca estándar.
"""

import argparse
import csv
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "datasets" / "papers"
SELECCION = DATASET_DIR / "seleccion.csv"
PDF_DIR = DATASET_DIR / "pdf"

API_URL = "https://export.arxiv.org/api/query"
OAI_URL = "https://export.arxiv.org/oai2"
USER_AGENT = "multimodal-tiny-database-engine/1.0 (proyecto academico BD2; corpus RAG)"
PAUSA = 3.0  # segundos entre peticiones (términos de uso de la API de arXiv)

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
OAI_ARXIV = "{http://arxiv.org/OAI/arXiv/}"
LICENCIA_POR_DEFECTO = "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"

CAMPOS = ("arxiv_id", "version", "titulo", "autores", "anio", "abstract",
          "categoria", "url_pdf", "licencia", "tema")

DB_IR = "cat:cs.DB OR cat:cs.IR OR cat:cs.DS"
NLP_IR = "cat:cs.IR OR cat:cs.CL OR cat:cs.LG"

# (tema, expresión de búsqueda, categorías, máximo de resultados).
TEMAS = (
    ("ann_grafos", 'abs:"nearest neighbor" AND (abs:graph OR abs:HNSW)', DB_IR + " OR cat:cs.LG OR cat:cs.CV", 30),
    ("cuantizacion_ivf", 'abs:"product quantization" OR abs:"inverted file"', DB_IR + " OR cat:cs.LG OR cat:cs.CV", 25),
    ("lsh", 'abs:"locality sensitive hashing"', DB_IR, 20),
    ("bd_vectoriales", 'abs:"vector database" OR abs:"vector search"', DB_IR, 25),
    ("bm25_indice_invertido", 'abs:BM25 OR abs:"inverted index"', "cat:cs.IR OR cat:cs.DB", 25),
    ("recuperacion_densa", 'abs:"dense retrieval" OR abs:"dense passage retrieval"', NLP_IR, 25),
    ("recuperacion_dispersa", 'abs:"learned sparse retrieval" OR abs:SPLADE', NLP_IR, 15),
    ("rag", 'abs:"retrieval-augmented generation" OR abs:"retrieval augmented generation"', NLP_IR, 35),
    ("indices_espaciales", 'abs:"R-tree" OR abs:"spatial index"', "cat:cs.DB OR cat:cs.DS OR cat:cs.CG", 20),
    ("indices_aprendidos", 'abs:"learned index"', DB_IR, 15),
    ("estructuras_disco", 'abs:"B+-tree" OR abs:"LSM-tree" OR abs:"extendible hashing"', "cat:cs.DB OR cat:cs.DS", 20),
    ("optimizacion_consultas", 'abs:"query optimization" OR abs:"cardinality estimation"', "cat:cs.DB", 20),
)

# Papers fundamentales que deben estar sí o sí (se validan contra la API).
SEMILLAS = (
    "1603.09320",  # HNSW (Malkov y Yashunin)
    "1702.08734",  # FAISS: billion-scale similarity search with GPUs
    "1707.00143",  # NSG: navigating spreading-out graph
    "1908.10396",  # ScaNN: anisotropic vector quantization
    "2101.12631",  # Survey/benchmark de ANN basado en grafos
    "1712.01208",  # The case for learned index structures
    "2005.11401",  # RAG (Lewis et al.)
    "2004.04906",  # Dense Passage Retrieval
    "2004.12832",  # ColBERT
    "2112.01488",  # ColBERTv2
    "2007.00808",  # ANCE
    "2002.08909",  # REALM
    "2007.01282",  # Fusion-in-Decoder
    "2112.04426",  # RETRO
    "2112.09118",  # Contriever
    "2107.05720",  # SPLADE
    "2104.08663",  # BEIR
    "1611.09268",  # MS MARCO
    "1908.10084",  # Sentence-BERT
    "2212.10496",  # HyDE
    "2307.03172",  # Lost in the Middle
    "2310.11511",  # Self-RAG
    "2312.10997",  # Survey de RAG para LLMs
)


class ClienteArxiv:
    """HTTP con pausa obligatoria entre peticiones y reintentos ante 429/503."""

    def __init__(self, pausa=PAUSA, reintentos=4, abrir=urllib.request.urlopen):
        self.pausa, self.reintentos, self._abrir = pausa, reintentos, abrir
        self._ultima = 0.0

    def get(self, url, params=None):
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        for intento in range(self.reintentos + 1):
            espera = self._ultima + self.pausa - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            self._ultima = time.monotonic()
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with self._abrir(request, timeout=120) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503) or intento == self.reintentos:
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if intento == self.reintentos:
                    raise
            time.sleep(self.pausa * 2 ** (intento + 1))
        raise RuntimeError("inalcanzable")


def _texto(nodo):
    return re.sub(r"\s+", " ", (nodo.text if nodo is not None else "") or "").strip()


def separar_version(identificador):
    """'http://arxiv.org/abs/2005.11401v4' -> ('2005.11401', 'v4')."""
    identificador = identificador.rsplit("/abs/", 1)[-1]
    match = re.fullmatch(r"(.+?)(v\d+)?", identificador)
    return match.group(1), match.group(2) or ""


def parse_feed(xml_bytes, tema=""):
    """Convierte el Atom de la API en filas con los CAMPOS (licencia vacía)."""
    root = ET.fromstring(xml_bytes)
    filas = []
    for entry in root.findall(f"{ATOM}entry"):
        id_nodo = entry.find(f"{ATOM}id")
        if id_nodo is None or "/abs/" not in (id_nodo.text or ""):
            continue  # la API devuelve una entrada "Error" ante IDs inválidos
        arxiv_id, version = separar_version(_texto(id_nodo))
        primaria = entry.find(f"{ARXIV}primary_category")
        pdf = next((link.get("href") for link in entry.findall(f"{ATOM}link")
                    if link.get("title") == "pdf"), f"https://arxiv.org/pdf/{arxiv_id}{version}")
        filas.append({
            "arxiv_id": arxiv_id,
            "version": version,
            "titulo": _texto(entry.find(f"{ATOM}title")),
            "autores": "; ".join(_texto(a.find(f"{ATOM}name")) for a in entry.findall(f"{ATOM}author")),
            "anio": _texto(entry.find(f"{ATOM}published"))[:4],
            "abstract": _texto(entry.find(f"{ATOM}summary")),
            "categoria": primaria.get("term") if primaria is not None else "",
            "url_pdf": pdf.replace("http://", "https://"),
            "licencia": "",
            "tema": tema,
        })
    return filas


def parse_licencia(xml_bytes):
    """Licencia del registro OAI-PMH (formato arXiv); por defecto la no exclusiva de arXiv."""
    nodo = ET.fromstring(xml_bytes).find(f".//{OAI_ARXIV}license")
    return _texto(nodo) or LICENCIA_POR_DEFECTO


def buscar(cliente, expresion, categorias, maximo, tema):
    params = {"search_query": f"({categorias}) AND ({expresion})", "start": 0,
              "max_results": maximo, "sortBy": "relevance", "sortOrder": "descending"}
    return parse_feed(cliente.get(API_URL, params), tema)


def por_ids(cliente, ids, tema="semilla"):
    filas = []
    for inicio in range(0, len(ids), 50):
        lote = ids[inicio:inicio + 50]
        filas += parse_feed(cliente.get(API_URL, {"id_list": ",".join(lote), "max_results": len(lote)}), tema)
    return filas


def seleccionar(cliente, maximo=250, temas=TEMAS, semillas=SEMILLAS, licencias=True, log=print):
    """Semillas primero; luego round-robin entre temas para que el corte sea balanceado."""
    elegidos, vistos = [], set()

    def agregar(fila):
        if fila["arxiv_id"] not in vistos and len(elegidos) < maximo:
            vistos.add(fila["arxiv_id"])
            elegidos.append(fila)

    semillas_ok = por_ids(cliente, list(semillas)) if semillas else []
    faltan = set(semillas) - {fila["arxiv_id"] for fila in semillas_ok}
    if faltan:
        log(f"Aviso: semillas no encontradas en arXiv: {sorted(faltan)}")
    for fila in semillas_ok:
        agregar(fila)
    log(f"Semillas: {len(semillas_ok)}")

    resultados = []
    for tema, expresion, categorias, tope in temas:
        filas = buscar(cliente, expresion, categorias, tope, tema)
        log(f"Tema {tema}: {len(filas)} resultados")
        resultados.append(filas)
    for posicion in range(max((len(f) for f in resultados), default=0)):
        for filas in resultados:
            if posicion < len(filas):
                agregar(filas[posicion])

    if licencias:
        for numero, fila in enumerate(elegidos, 1):
            identificador = f"oai:arXiv.org:{fila['arxiv_id']}"
            try:
                fila["licencia"] = parse_licencia(cliente.get(
                    OAI_URL, {"verb": "GetRecord", "identifier": identificador, "metadataPrefix": "arXiv"}))
            except (urllib.error.URLError, TimeoutError, ConnectionError, ET.ParseError) as exc:
                log(f"Aviso: sin licencia para {fila['arxiv_id']} ({exc}); se asume la por defecto")
                fila["licencia"] = LICENCIA_POR_DEFECTO
            if numero % 25 == 0:
                log(f"Licencias: {numero}/{len(elegidos)}")
    else:
        for fila in elegidos:
            fila["licencia"] = fila["licencia"] or LICENCIA_POR_DEFECTO
    return elegidos


def escribir_seleccion(filas, path=SELECCION):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CAMPOS)
        writer.writeheader()
        writer.writerows(filas)


def leer_seleccion(path=SELECCION):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CAMPOS:
            raise ValueError(f"Cabecera incorrecta en {path}; se esperaba {CAMPOS}")
        filas = list(reader)
    ids = [fila["arxiv_id"] for fila in filas]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: arxiv_id duplicados")
    return filas


def nombre_pdf(arxiv_id):
    """IDs antiguos tienen '/': cs/0101001 -> cs_0101001.pdf."""
    return arxiv_id.replace("/", "_") + ".pdf"


def descargar(cliente, filas, destino=PDF_DIR, log=print):
    """Descarga solo lo que falta; un PDF ya presente y válido no se vuelve a pedir."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    nuevos = fallidos = 0
    for numero, fila in enumerate(filas, 1):
        path = destino / nombre_pdf(fila["arxiv_id"])
        if path.is_file() and path.read_bytes()[:5] == b"%PDF-":
            continue
        try:
            datos = cliente.get(fila["url_pdf"])
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            log(f"[{numero}/{len(filas)}] Error {fila['arxiv_id']}: {exc}")
            fallidos += 1
            continue
        if datos[:5] != b"%PDF-":
            log(f"[{numero}/{len(filas)}] {fila['arxiv_id']}: la respuesta no es un PDF")
            fallidos += 1
            continue
        temporal = path.with_suffix(".part")
        temporal.write_bytes(datos)
        temporal.replace(path)
        nuevos += 1
        log(f"[{numero}/{len(filas)}] {fila['arxiv_id']} ({len(datos) // 1024} KB)")
    return {"nuevos": nuevos, "fallidos": fallidos, "total": len(filas)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Corpus de papers de arXiv (issue #97)")
    sub = parser.add_subparsers(dest="comando", required=True)
    sel = sub.add_parser("seleccionar", help="consulta la API y escribe seleccion.csv")
    sel.add_argument("--maximo", type=int, default=250, help="papers a elegir (100–300)")
    sel.add_argument("--salida", type=Path, default=SELECCION)
    sel.add_argument("--sin-licencias", action="store_true", help="no consultar OAI-PMH")
    sel.add_argument("--forzar", action="store_true", help="sobrescribir una selección existente")
    des = sub.add_parser("descargar", help="descarga los PDFs de seleccion.csv")
    des.add_argument("--seleccion", type=Path, default=SELECCION)
    des.add_argument("--destino", type=Path, default=PDF_DIR)
    args = parser.parse_args(argv)
    cliente = ClienteArxiv()

    if args.comando == "seleccionar":
        if not 1 <= args.maximo <= 2000:
            parser.error("--maximo fuera de rango")
        if args.salida.exists() and not args.forzar:
            parser.error(f"{args.salida} ya existe: es la selección congelada; use --forzar para rehacerla")
        filas = seleccionar(cliente, args.maximo, licencias=not args.sin_licencias)
        escribir_seleccion(filas, args.salida)
        print(f"{len(filas)} papers en {args.salida}")
    else:
        resultado = descargar(cliente, leer_seleccion(args.seleccion), args.destino)
        print(resultado)
        if resultado["fallidos"]:
            sys.exit(1)


if __name__ == "__main__":
    main()