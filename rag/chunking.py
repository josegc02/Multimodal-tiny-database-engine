"""Extracción de texto de PDFs y fragmentación en trozos de 200–500 palabras.

Cada fragmento recuerda la página donde empieza (``pagina``) y donde
termina (``pagina_fin``), para poder citar la fuente en las respuestas RAG.
Los cortes prefieren el final de una oración: un fragmento se cierra al
llegar a ``objetivo`` palabras en el primer punto final, o a la fuerza al
llegar a ``maximo``. Un resto final menor a ``minimo`` se reparte con el
fragmento anterior. Solo un documento entero más corto que ``minimo``
puede producir un fragmento pequeño.
"""

import re
import unicodedata
import logging

MINIMO, OBJETIVO, MAXIMO = 200, 350, 500

_FIN_ORACION = re.compile(r"[.!?][\"')\]]*$")
_GUION_FIN_LINEA = re.compile(r"([a-z])-\n\s*([a-z])")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_REFERENCIAS = re.compile(r"^\s*(?:[0-9IVX]+\.?\s+)?(?:references|bibliography|referencias)\s*$", re.IGNORECASE)


def limpiar(texto):
    """Normaliza ligaduras (NFKC), une palabras partidas por guion y quita controles."""
    texto = (texto or "").encode("utf-16", "surrogatepass").decode("utf-16", "replace").replace("\ufffd", "")
    texto = unicodedata.normalize("NFKC", texto)
    texto = _CONTROL.sub(" ", texto.replace("\r\n", "\n").replace("\r", "\n"))
    return _GUION_FIN_LINEA.sub(r"\1\2", texto)


def quitar_referencias(paginas):
    """Corta en el último encabezado 'References' de la segunda mitad del documento.

    Recibe y devuelve una lista de (numero_pagina, texto). La bibliografía
    es ruido para la recuperación: muchos nombres propios y títulos ajenos.
    """
    if not paginas:
        return paginas
    mitad = len(paginas) // 2
    for posicion in range(len(paginas) - 1, mitad - 1, -1):
        numero, texto = paginas[posicion]
        lineas = texto.split("\n")
        for linea in range(len(lineas) - 1, -1, -1):
            if _REFERENCIAS.match(lineas[linea]):
                antes = "\n".join(lineas[:linea])
                return paginas[:posicion] + ([(numero, antes)] if antes.strip() else [])
    return paginas


def palabras_con_pagina(paginas):
    for numero, texto in paginas:
        for palabra in limpiar(texto).split():
            yield palabra, numero


def _fragmento(palabras):
    return {"pagina": palabras[0][1], "pagina_fin": palabras[-1][1],
            "palabras": len(palabras), "texto": " ".join(p for p, _ in palabras)}


def fragmentar(paginas, minimo=MINIMO, objetivo=OBJETIVO, maximo=MAXIMO):
    """paginas: [(numero_pagina, texto)] -> [{orden, pagina, pagina_fin, palabras, texto}]."""
    if not 0 < minimo <= objetivo <= maximo or maximo < 2 * minimo:
        raise ValueError("Se requiere 0 < minimo <= objetivo <= maximo y maximo >= 2*minimo")
    grupos, actual = [], []
    for palabra, pagina in palabras_con_pagina(paginas):
        actual.append((palabra, pagina))
        if len(actual) >= maximo or (len(actual) >= objetivo and _FIN_ORACION.search(palabra)):
            grupos.append(actual)
            actual = []
    if actual:
        if grupos and len(actual) < minimo:
            junto = grupos.pop() + actual
            if len(junto) <= maximo:
                grupos.append(junto)
            else:  # entre maximo y maximo+minimo: dos mitades, ambas >= minimo
                corte = _corte_balanceado(junto, minimo)
                grupos += [junto[:corte], junto[corte:]]
        else:
            grupos.append(actual)
    return [dict(orden=orden, **_fragmento(grupo)) for orden, grupo in enumerate(grupos, 1)]


def _corte_balanceado(palabras, minimo):
    """Corte cerca de la mitad, preferentemente tras un fin de oración."""
    mitad = len(palabras) // 2
    candidatos = [i for i in range(minimo, len(palabras) - minimo + 1)
                  if _FIN_ORACION.search(palabras[i - 1][0])]
    return min(candidatos, key=lambda i: abs(i - mitad), default=mitad)


def extraer_paginas(pdf_path):
    """[(numero_pagina, texto)] con numeración desde 1, usando pypdf."""
    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(str(pdf_path))
    paginas = []
    for numero, page in enumerate(reader.pages, 1):
        try:
            texto = page.extract_text() or ""
        except Exception:  # una página corrupta no invalida el paper completo
            texto = ""
        paginas.append((numero, texto))
    return paginas