"""Asistente académico (opción A, issue #98): pregunta -> BM25 -> LLM con citas.

Flujo de ``preguntar``:

1. La pregunta (en español) pasa a palabras clave en inglés, porque BM25
   compara términos y los papers están en inglés. Con LLM se le pide al
   modelo; sin LLM (o con BD2_PALABRAS_CLAVE=local) se usa un glosario
   pequeño (``palabras_clave_locales``) y cada pregunta gasta una sola petición.
2. Top-k fragmentos con ``MATCH(texto, ...) USING BM25`` sobre ``fragmentos``
   y su metadata con una segunda consulta a ``papers``: el motor no admite
   ``MATCH`` junto con ``JOIN``.
3. Prompt que obliga a responder solo con esos fragmentos y a citar con
   ``[n]``; si no ayudan, el modelo debe decirlo.

El LLM se elige con BD2_LLM: ``gemini`` (por defecto, capa gratuita, key en
GEMINI_API_KEY), ``claude`` (ANTHROPIC_API_KEY) o ``ninguno``. BD2_LLM_MODELO
cambia el modelo del proveedor elegido.

Las tablas son las del corpus del #97 (``rag/corpus.py``)::

    papers (id, arxiv_id, titulo, autores, anio, abstract, ..., url, ...)
    fragmentos (id, paper_id, orden, pagina, pagina_fin, palabras, texto)
"""

from __future__ import annotations

import os
import time
import re
import unicodedata
from typing import Callable, Protocol

MODELO_CLAUDE = "claude-haiku-5-5"
MODELO_GEMINI = "gemini-3.1-flash-lite"  # el más rápido de la capa gratuita (~2-3 s)
PROVEEDORES = ("gemini", "claude", "ninguno")
MAX_PALABRAS_CLAVE = 16  # modo sin LLM: todas las traducidas de la pregunta
MAX_PALABRAS_LLM = 5     # con LLM: solo las más específicas (benchmarks/asistente)
MAX_POR_PAPER = 2      # fragmentos de un mismo documento en la respuesta, para variar las fuentes
CANDIDATOS_POR_K = 5   # se piden k * 5 fragmentos a BM25 y luego se aplica MAX_POR_PAPER
UMBRAL_RELATIVO = 0.6  # se descarta un fragmento con menos del 60 % del puntaje del primero
SIN_FRAGMENTOS = "No encontré fragmentos de los papers relacionados con la pregunta."

# Pocas palabras y en inglés, medido en benchmarks/asistente: cada término de
# más (y cada término en español) suma puntaje a fragmentos que no tratan el
# tema. Las diapositivas del curso igual aparecen, porque usan los términos
# técnicos en inglés (buffer manager, write-ahead log, B+ tree...).
PROMPT_PALABRAS_CLAVE = (
    "Eres parte de un buscador BM25 sobre papers académicos y clases de bases de datos y "
    "recuperación de información. Convierte la pregunta del usuario en 5 palabras clave en "
    "inglés. Empieza por el término técnico de la pregunta traducido literalmente (buffer "
    "manager, extendible hashing, horizontal fragmentation) o su sigla (HNSW, SPIMI, BM25), "
    "y sigue con términos técnicos o sinónimos útiles. No incluyas palabras vacías. Responde "
    "solo con las palabras separadas por espacios, sin explicación ni puntuación."
)

PROMPT_RESPUESTA = (
    "Eres un asistente académico. Responde en español a la pregunta usando SOLO la "
    "información de los fragmentos numerados que se te dan; no uses conocimiento propio.\n"
    "- Después de cada afirmación cita el fragmento que la respalda con su número entre "
    "corchetes, por ejemplo [1] o [2][3].\n"
    "- Si los fragmentos no contienen información suficiente para responder, dilo "
    "claramente, no inventes nada y no pongas ninguna cita.\n"
    "- Sé breve: como máximo 150 palabras, en uno o dos párrafos.\n"
    "- Escribe texto simple: sin LaTeX ni signos $, sin tablas ni encabezados."
)

# Modo sin LLM. Primero se reemplazan frases de varias palabras y luego cada
# palabra de la pregunta (en minúsculas y sin tildes) con el glosario.
FRASES = (
    (r"\barbol(?:es)? b\+?(?![a-z0-9])", " b-tree "),
    (r"\bbases? de datos\b", " database "),
    (r"\bsensibles? a la localidad\b", " locality sensitive "),
)

GLOSARIO = {
    "indice": "index", "indices": "index", "invertido": "inverted", "busqueda": "search",
    "buscar": "search", "recuperacion": "retrieval", "consulta": "query", "consultas": "query",
    "vecino": "neighbor", "vecinos": "neighbors", "cercano": "nearest", "cercanos": "nearest",
    "aproximado": "approximate", "aproximada": "approximate", "aproximados": "approximate",
    "grafo": "graph", "grafos": "graph", "jerarquico": "hierarchical", "navegable": "navigable",
    "mundo": "world", "pequeno": "small", "vector": "vector", "vectores": "vector",
    "vectorial": "vector", "vectoriales": "vector", "similitud": "similarity",
    "distancia": "distance", "documento": "document", "documentos": "document",
    "termino": "term", "terminos": "term", "frecuencia": "frequency", "ranking": "ranking",
    "base": "database", "bases": "database", "datos": "data", "arbol": "tree",
    "arboles": "tree", "espacial": "spatial", "espaciales": "spatial", "hash": "hashing",
    "dispersion": "hashing", "cuantizacion": "quantization", "producto": "product",
    "agrupamiento": "clustering", "cluster": "clustering", "aprendido": "learned",
    "aprendidos": "learned", "optimizacion": "optimization", "optimizador": "optimizer",
    "costo": "cost", "plan": "plan", "denso": "dense", "densa": "dense",
    "disperso": "sparse", "dispersa": "sparse", "embedding": "embedding",
    "embeddings": "embedding", "generacion": "generation", "aumentada": "augmented",
    "modelo": "model", "modelos": "model", "lenguaje": "language", "rendimiento": "performance",
    "memoria": "memory", "disco": "disk", "compresion": "compression", "escalable": "scalable",
    "particion": "partition", "particiones": "partition", "texto": "text", "imagen": "image",
    "imagenes": "image", "audio": "audio", "palabra": "word", "palabras": "word",
    "cardinalidad": "cardinality", "estima": "estimation", "estimar": "estimation",
    "estimacion": "estimation", "selectividad": "selectivity", "localidad": "locality",
    "aprendida": "learned", "aprendidas": "learned", "rango": "range", "escritura": "write",
    "lectura": "read", "transaccion": "transaction", "transacciones": "transaction",
}

PALABRAS_VACIAS = set(
    "que cual cuales como cuando donde quien por para con sin sobre entre de del la las el "
    "los un una unos unas y o u e a al en es son se su sus lo le les mas menos muy ya hay "
    "explica explicame dime describe define cuentame funciona funcionan sirve diferencia "
    "diferencias ventaja ventajas usa usan uso usar tiene tienen hace hacen esto este esta "
    "estos estas eso ese esa frente versus vs puede pueden debe deben cada otro otra "
    "otros otras mejor peor".split()
)


class LLM(Protocol):
    """Lo único que el asistente necesita de un modelo: texto de entrada, texto de salida."""

    def completar(self, sistema: str, mensaje: str, max_tokens: int) -> str: ...


class ErrorAsistente(Exception):
    """Error de los datos o de la consulta (la API responde 400)."""


class ErrorLLM(Exception):
    """El LLM no respondió (la API responde 502)."""


class ClienteClaude:
    """LLM con la API de Claude. La API key se lee de ``ANTHROPIC_API_KEY``.

    El modelo se cambia con ``BD2_LLM_MODELO``. El cliente se crea en la primera
    llamada, para que la API pueda arrancar aunque no haya credenciales.
    """

    def __init__(self, modelo: str | None = None, cliente=None):
        self.modelo = modelo or os.environ.get("BD2_LLM_MODELO") or MODELO_CLAUDE
        self._cliente = cliente

    def completar(self, sistema: str, mensaje: str, max_tokens: int) -> str:
        import anthropic

        if self._cliente is None:
            self._cliente = anthropic.Anthropic()
        try:
            respuesta = self._cliente.messages.create(
                model=self.modelo,
                max_tokens=max_tokens,
                system=sistema,
                messages=[{"role": "user", "content": mensaje}],
                output_config={"effort": "low"},
            )
        except anthropic.AuthenticationError as exc:
            raise ErrorLLM("API key inválida o ausente: configure ANTHROPIC_API_KEY "
                           "o pregunte con usar_llm=false") from exc
        except anthropic.RateLimitError as exc:
            raise ErrorLLM("Límite de peticiones del LLM alcanzado; intente en un momento") from exc
        except anthropic.APIStatusError as exc:
            raise ErrorLLM(f"El LLM respondió con error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ErrorLLM("No hay conexión con el LLM; pregunte con usar_llm=false") from exc
        except anthropic.AnthropicError as exc:  # p. ej., no se encontró ninguna credencial
            raise ErrorLLM(f"No se pudo usar el LLM: {exc}") from exc
        if respuesta.stop_reason == "refusal":
            raise ErrorLLM("El LLM se negó a responder esta pregunta")
        return "".join(b.text for b in respuesta.content if b.type == "text").strip()


class ClienteGemini:
    """LLM con la API de Gemini (Google AI Studio). La key se lee de ``GEMINI_API_KEY``.

    Por defecto usa Flash-Lite, que entra en la capa gratuita. El modelo se cambia
    con ``BD2_LLM_MODELO``. Como el de Claude, el cliente se crea en la primera llamada.
    """

    def __init__(self, modelo: str | None = None, cliente=None):
        self.modelo = modelo or os.environ.get("BD2_LLM_MODELO") or MODELO_GEMINI
        self._cliente = cliente

    def completar(self, sistema: str, mensaje: str, max_tokens: int) -> str:
        from google import genai
        from google.genai import errors, types

        try:
            if self._cliente is None:
                # Reintenta solo si Google está saturado (500/503), no si se acabó la cuota.
                reintentos = types.HttpRetryOptions(attempts=3, initial_delay=2.0,
                                                    http_status_codes=[500, 502, 503, 504])
                self._cliente = genai.Client(http_options=types.HttpOptions(retry_options=reintentos))
            respuesta = self._cliente.models.generate_content(
                model=self.modelo,
                contents=mensaje,
                config=types.GenerateContentConfig(system_instruction=sistema,
                                                   max_output_tokens=max_tokens),
            )
        except errors.ClientError as exc:
            if exc.code == 429:
                raise ErrorLLM("Se acabó la cuota gratuita de Gemini por ahora (se renueva cada "
                               "minuto y cada día); intente luego o use usar_llm=false") from exc
            if exc.code in (400, 401, 403) and "key" in str(exc).lower():
                raise ErrorLLM("API key de Gemini inválida: revise GEMINI_API_KEY") from exc
            raise ErrorLLM(f"Gemini respondió con error {exc.code}: {exc.message}") from exc
        except errors.APIError as exc:
            raise ErrorLLM(f"Gemini respondió con error {exc.code}: {exc.message}") from exc
        except ValueError as exc:  # el SDK no encontró ninguna API key
            raise ErrorLLM("Falta la API key: configure GEMINI_API_KEY "
                           "o pregunte con usar_llm=false") from exc
        except OSError as exc:
            raise ErrorLLM("No hay conexión con el LLM; pregunte con usar_llm=false") from exc
        bloqueo = getattr(respuesta.prompt_feedback, "block_reason", None)
        if bloqueo:
            raise ErrorLLM(f"Gemini bloqueó la pregunta ({bloqueo})")
        return (respuesta.text or "").strip()


def crear_llm(proveedor: str | None = None) -> LLM | None:
    """El LLM según BD2_LLM (``gemini`` por defecto). ``ninguno`` lo apaga."""
    proveedor = (proveedor or os.environ.get("BD2_LLM") or "gemini").strip().lower()
    if proveedor not in PROVEEDORES:
        raise ValueError(f"BD2_LLM debe ser uno de {', '.join(PROVEEDORES)}; se recibió {proveedor!r}")
    if proveedor == "ninguno":
        return None
    return ClienteGemini() if proveedor == "gemini" else ClienteClaude()


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def _terminos(texto: str) -> list[str]:
    """Palabras ASCII (letras, dígitos y guiones), sin repetir, en orden."""
    vistos: dict[str, None] = {}
    for palabra in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", _sin_tildes(texto).lower()):
        vistos.setdefault(palabra, None)
    return list(vistos)


def palabras_clave_locales(pregunta: str) -> str:
    """Modo sin LLM: quita palabras vacías y traduce con el glosario.

    Las palabras que no están en el glosario se conservan: suelen ser siglas o
    términos que ya están en inglés (HNSW, BM25, B+tree, LSM...). No se agregan
    las originales en español: en benchmarks/asistente bajaban la precisión@5
    de 0.83 a 0.64.
    """
    texto = _sin_tildes(pregunta).lower()
    for patron, reemplazo in FRASES:
        texto = re.sub(patron, reemplazo, texto)
    terminos = []
    for palabra in _terminos(texto):
        if palabra in PALABRAS_VACIAS or len(palabra) < 2:
            continue
        traducida = GLOSARIO.get(palabra, palabra)
        if traducida not in terminos:
            terminos.append(traducida)
    return " ".join(terminos[:MAX_PALABRAS_CLAVE])


def palabras_clave(pregunta: str, llm: LLM | None) -> str:
    """Palabras clave en inglés para MATCH. Siempre devuelve solo [a-z0-9-] y espacios."""
    if llm is not None:
        consulta = " ".join(_terminos(llm.completar(PROMPT_PALABRAS_CLAVE, pregunta, 4000))
                            [:MAX_PALABRAS_LLM])
        if consulta:
            return consulta
    return palabras_clave_locales(pregunta)


def _consultar(ejecutar: Callable, sql: str):
    resultado = ejecutar(sql)
    if resultado.tiene_error:
        if "no existe" in resultado.error.lower():
            raise ErrorAsistente(f"{resultado.error}. Cargue el corpus con "
                                 "'python -m rag.corpus cargar' (issue #97)")
        raise ErrorAsistente(resultado.error)
    return [dict(zip(resultado.columnas, fila)) for fila in resultado.filas]


def recuperar(ejecutar: Callable, consulta: str, k: int) -> list[dict]:
    """Top-k fragmentos por BM25, cada uno con el título, autores, año y URL de su paper.

    Se toman a lo más MAX_POR_PAPER fragmentos de cada documento, para que un paper
    largo que repite los términos no ocupe todo el top-k, y se descartan los que
    no llegan a UMBRAL_RELATIVO del puntaje del primero: suelen coincidir solo en
    un término general.
    """
    if not consulta:
        return []
    candidatos = _consultar(ejecutar, (
        "SELECT id, paper_id, pagina, pagina_fin, texto, SCORE() AS puntaje FROM fragmentos "
        f"WHERE MATCH(texto, '{consulta}') USING BM25 ORDER BY puntaje DESC "
        f"LIMIT {int(k) * CANDIDATOS_POR_K}"))
    minimo = UMBRAL_RELATIVO * float(candidatos[0]["puntaje"]) if candidatos else 0.0
    fragmentos, por_paper = [], {}
    for fragmento in candidatos:
        if float(fragmento["puntaje"]) < minimo:
            break  # vienen ordenados: los siguientes tampoco llegan
        usados = por_paper.get(fragmento["paper_id"], 0)
        if usados < MAX_POR_PAPER:
            por_paper[fragmento["paper_id"]] = usados + 1
            fragmentos.append(fragmento)
            if len(fragmentos) == k:
                break
    if not fragmentos:
        return []
    ids = ", ".join(str(int(f["paper_id"])) for f in fragmentos)
    papers = {p["id"]: p for p in _consultar(
        ejecutar, f"SELECT id, titulo, autores, anio, url FROM papers WHERE id IN ({ids})")}
    salida = []
    for n, fragmento in enumerate(fragmentos, start=1):
        paper = papers.get(fragmento["paper_id"], {})
        salida.append({
            "n": n,
            "id": fragmento["id"],
            "paper_id": fragmento["paper_id"],
            "titulo": paper.get("titulo"),
            "autores": paper.get("autores"),
            "anio": paper.get("anio"),
            "url": paper.get("url"),
            "pagina": fragmento["pagina"],
            "pagina_fin": fragmento["pagina_fin"],
            "puntaje": round(float(fragmento["puntaje"]), 4),
            "texto": fragmento["texto"],
        })
    return salida


def mensaje_respuesta(pregunta: str, fragmentos: list[dict]) -> str:
    """Los fragmentos numerados y la pregunta, tal como los lee el LLM."""
    bloques = []
    for f in fragmentos:
        paginas = (f"pág. {f['pagina']}" if f["pagina_fin"] in (None, f["pagina"])
                   else f"págs. {f['pagina']}-{f['pagina_fin']}")
        anio = f" ({f['anio']})" if f["anio"] else ""
        bloques.append(f"[{f['n']}] {f['titulo'] or 'Paper sin título'}{anio}, {paginas}\n{f['texto']}")
    return "Fragmentos:\n\n" + "\n\n".join(bloques) + f"\n\nPregunta: {pregunta}"


def citas(texto: str, total: int) -> list[int]:
    """Números citados como [n] o [n, m], válidos y sin repetir, en orden de aparición."""
    encontradas: list[int] = []
    for grupo in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", texto):
        for numero in map(int, grupo.split(",")):
            if 1 <= numero <= total and numero not in encontradas:
                encontradas.append(numero)
    return encontradas


def preguntar(ejecutar: Callable, pregunta: str, k: int = 5, llm: LLM | None = None,
              palabras_con_llm: bool = True) -> dict:
    """Responde una pregunta. ``ejecutar`` corre SQL en el motor y devuelve su ``Resultado``.

    Sin ``llm`` (modo sin LLM) solo se devuelven los fragmentos, sin redactar respuesta.
    Con ``palabras_con_llm=False`` las palabras clave salen del glosario local y el
    LLM se llama una sola vez (útil con la cuota gratuita de Gemini).
    """
    pregunta = pregunta.strip()
    if not pregunta:
        raise ErrorAsistente("La pregunta está vacía")
    inicio = time.perf_counter()
    sentencias: list[str] = []
    ms_motor = 0.0

    def ejecutar_y_medir(sql: str):
        nonlocal ms_motor
        t = time.perf_counter()
        resultado = ejecutar(sql)
        ms_motor += (time.perf_counter() - t) * 1000
        sentencias.append(sql)
        return resultado

    t = time.perf_counter()
    consulta = palabras_clave(pregunta, llm if palabras_con_llm else None)
    s_palabras = time.perf_counter() - t
    fragmentos = recuperar(ejecutar_y_medir, consulta, k)
    respuesta, s_redaccion = None, None
    if llm is not None:
        t = time.perf_counter()
        respuesta = (llm.completar(PROMPT_RESPUESTA, mensaje_respuesta(pregunta, fragmentos), 16000)
                     if fragmentos else SIN_FRAGMENTOS)
        s_redaccion = round(time.perf_counter() - t, 2) if fragmentos else None
    return {
        "pregunta": pregunta,
        "consulta": consulta,
        "modo": "llm" if llm is not None else "sin_llm",
        "respuesta": respuesta,
        "citas": citas(respuesta, len(fragmentos)) if respuesta else [],
        "fragmentos": fragmentos,
        # Lo que hizo el motor, para mostrarlo en el front ("Cómo se respondió").
        "traza": {
            "sql": sentencias,
            "ms_motor": round(ms_motor, 1),
            "documentos": len({f["paper_id"] for f in fragmentos}),
            "palabras_con_llm": llm is not None and palabras_con_llm,
            "s_palabras": round(s_palabras, 2) if llm is not None and palabras_con_llm else None,
            "s_redaccion": s_redaccion,
            "s_total": round(time.perf_counter() - inicio, 2),
            "modelo": getattr(llm, "modelo", None),
        },
    }


# --- Biblioteca y subida de PDF (front del asistente, #99) -------------------

COLUMNAS_PAPER = "id, arxiv_id, titulo, autores, anio, abstract, categoria, fuente, url, licencia, tema"


def _literal(valor) -> str:
    return "'" + str(valor).replace("'", "''") + "'"


def listar_documentos(ejecutar: Callable) -> list[dict]:
    """Todos los documentos (sin abstract) con su número de fragmentos."""
    conteos = {f["paper_id"]: f["n"] for f in _consultar(
        ejecutar, "SELECT paper_id, COUNT(*) AS n FROM fragmentos GROUP BY paper_id")}
    documentos = _consultar(ejecutar, "SELECT id, arxiv_id, titulo, autores, anio, fuente, url, tema FROM papers")
    for documento in documentos:
        documento["fragmentos"] = conteos.get(documento["id"], 0)
    return sorted(documentos, key=lambda d: d["id"])


def obtener_documento(ejecutar: Callable, paper_id: int) -> dict | None:
    """Un documento con su abstract y todos sus fragmentos en orden."""
    filas = _consultar(ejecutar, f"SELECT {COLUMNAS_PAPER} FROM papers WHERE id = {int(paper_id)}")
    if not filas:
        return None
    documento = filas[0]
    documento["fragmentos"] = _consultar(ejecutar, (
        "SELECT id, orden, pagina, pagina_fin, palabras, texto FROM fragmentos "
        f"WHERE paper_id = {int(paper_id)} ORDER BY orden"))
    return documento


def indexar_pdf(ejecutar: Callable, paginas: list[tuple[int, str]], titulo: str, autores: str,
                anio: int, tema: str, fuente: str) -> dict:
    """Fragmenta un PDF ya extraído y lo inserta en papers y fragmentos.

    El índice SPIMI de fragmentos.texto se actualiza con el INSERT. Devuelve el
    id nuevo y lo que hizo cada paso, para mostrar el avance.
    """
    from rag.chunking import fragmentar, quitar_referencias

    titulo = titulo.strip()
    if not titulo:
        raise ErrorAsistente("El documento necesita un título")
    fragmentos = fragmentar(quitar_referencias(paginas))
    if not fragmentos:
        raise ErrorAsistente("El PDF no tiene texto extraíble (¿es un escaneo?)")
    paper_id = int(_consultar(ejecutar, "SELECT MAX(id) AS m FROM papers")[0]["m"] or 0) + 1
    primer_fragmento = int(_consultar(ejecutar, "SELECT MAX(id) AS m FROM fragmentos")[0]["m"] or 0) + 1
    t = time.perf_counter()
    _consultar(ejecutar, (
        f"INSERT INTO papers ({COLUMNAS_PAPER}) VALUES ({paper_id}, '', {_literal(titulo)}, "
        f"{_literal(autores.strip())}, {int(anio)}, '', {_literal(fuente)}, {_literal(fuente)}, '', "
        f"'Subido por el usuario', {_literal(tema)})"))
    filas = ", ".join(
        f"({primer_fragmento + i}, {paper_id}, {f['orden']}, {f['pagina']}, {f['pagina_fin']}, "
        f"{f['palabras']}, {_literal(f['texto'])})" for i, f in enumerate(fragmentos))
    _consultar(ejecutar, f"INSERT INTO fragmentos (id, paper_id, orden, pagina, pagina_fin, palabras, texto) VALUES {filas}")
    return {
        "id": paper_id,
        "paginas": len(paginas),
        "fragmentos": len(fragmentos),
        "palabras": sum(f["palabras"] for f in fragmentos),
        "ms_insercion": round((time.perf_counter() - t) * 1000, 1),
    }
