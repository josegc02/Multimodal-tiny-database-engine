"""Asistente académico (opción A, issue #98): pregunta -> BM25 -> LLM con citas.

Flujo de ``preguntar``:

1. La pregunta (en español) pasa a palabras clave en inglés, porque BM25
   compara términos y los papers están en inglés. Con LLM se le pide a
   Claude; sin LLM se usa un glosario pequeño (``palabras_clave_locales``).
2. Top-k fragmentos con ``MATCH(texto, ...) USING BM25`` sobre ``fragmentos``
   y su metadata con una segunda consulta a ``papers``: el motor no admite
   ``MATCH`` junto con ``JOIN``.
3. Prompt que obliga a responder solo con esos fragmentos y a citar con
   ``[n]``; si no ayudan, el modelo debe decirlo.

Las tablas son las del corpus del #97 (``rag/corpus.py``)::

    papers (id, arxiv_id, titulo, autores, anio, abstract, ..., url, ...)
    fragmentos (id, paper_id, orden, pagina, pagina_fin, palabras, texto)
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Callable, Protocol

MODELO_DEFECTO = "claude-haiku-5-5"
MAX_PALABRAS_CLAVE = 12
SIN_FRAGMENTOS = "No encontré fragmentos de los papers relacionados con la pregunta."

PROMPT_PALABRAS_CLAVE = (
    "Eres parte de un buscador BM25 sobre papers académicos en inglés de bases de datos y "
    "recuperación de información. Convierte la pregunta del usuario en 3 a 8 palabras clave "
    "en inglés que probablemente aparezcan en esos papers (términos técnicos, siglas como "
    "HNSW o BM25, sinónimos útiles). Responde solo con las palabras separadas por espacios, "
    "sin explicación ni puntuación."
)

PROMPT_RESPUESTA = (
    "Eres un asistente académico. Responde en español a la pregunta usando SOLO la "
    "información de los fragmentos numerados que se te dan; no uses conocimiento propio.\n"
    "- Después de cada afirmación cita el fragmento que la respalda con su número entre "
    "corchetes, por ejemplo [1] o [2][3].\n"
    "- Si los fragmentos no contienen información suficiente para responder, dilo "
    "claramente y no inventes nada.\n"
    "- Sé breve: uno a tres párrafos."
)

# Glosario para el modo sin LLM: palabras de la pregunta (sin tildes) -> términos en inglés.
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
}

PALABRAS_VACIAS = set(
    "que cual cuales como cuando donde quien por para con sin sobre entre de del la las el "
    "los un una unos unas y o u e a al en es son se su sus lo le les mas menos muy ya hay "
    "explica explicame dime describe define cuentame funciona funcionan sirve diferencia "
    "diferencias ventaja ventajas usa usan uso usar tiene tienen hace hacen esto este esta "
    "estos estas eso ese esa qué cuál cómo".split()
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
        self.modelo = modelo or os.environ.get("BD2_LLM_MODELO") or MODELO_DEFECTO
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
    términos que ya están en inglés (HNSW, BM25, B+tree, LSM...).
    """
    terminos = []
    for palabra in _terminos(pregunta):
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
                            [:MAX_PALABRAS_CLAVE])
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
    """Top-k fragmentos por BM25, cada uno con el título, autores, año y URL de su paper."""
    if not consulta:
        return []
    fragmentos = _consultar(ejecutar, (
        "SELECT id, paper_id, pagina, pagina_fin, texto, SCORE() AS puntaje FROM fragmentos "
        f"WHERE MATCH(texto, '{consulta}') USING BM25 ORDER BY puntaje DESC LIMIT {int(k)}"))
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


def preguntar(ejecutar: Callable, pregunta: str, k: int = 5, llm: LLM | None = None) -> dict:
    """Responde una pregunta. ``ejecutar`` corre SQL en el motor y devuelve su ``Resultado``.

    Sin ``llm`` (modo sin LLM) solo se devuelven los fragmentos, sin redactar respuesta.
    """
    pregunta = pregunta.strip()
    if not pregunta:
        raise ErrorAsistente("La pregunta está vacía")
    consulta = palabras_clave(pregunta, llm)
    fragmentos = recuperar(ejecutar, consulta, k)
    respuesta = None
    if llm is not None:
        respuesta = (llm.completar(PROMPT_RESPUESTA, mensaje_respuesta(pregunta, fragmentos), 16000)
                     if fragmentos else SIN_FRAGMENTOS)
    return {
        "pregunta": pregunta,
        "consulta": consulta,
        "modo": "llm" if llm is not None else "sin_llm",
        "respuesta": respuesta,
        "citas": citas(respuesta, len(fragmentos)) if respuesta else [],
        "fragmentos": fragmentos,
    }
