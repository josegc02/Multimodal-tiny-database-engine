"""Precisión de la recuperación del asistente (#98) sobre el corpus cargado.

Para cada pregunta de ``preguntas.json`` se recuperan los fragmentos como lo
hace el endpoint y se mide:

- precisión: fracción de los fragmentos devueltos (k como máximo; el umbral
  relativo puede devolver menos) que contienen al menos uno de los términos de
  evidencia de la pregunta (sin tildes, sin distinguir mayúsculas; un término
  puede ser una expresión regular como ``\\bwal\\b``);
- relevantes: total de fragmentos relevantes devueltos, para comprobar que la
  precisión no sube solo por devolver menos;
- acierto@1: si el primer fragmento es relevante;
- documentos distintos entre los k.

Las palabras clave que da el LLM se guardan en ``cache_palabras.json`` (por
versión del prompt), para repetir la medición sin gastar cuota.

Uso, desde la raíz y con el corpus cargado en ``data/app``::

    python -m benchmarks.asistente.precision            # LLM según BD2_LLM
    python -m benchmarks.asistente.precision --local    # glosario, sin LLM
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from api import asistente
from frontend.motor import Motor

DIR = Path(__file__).resolve().parent
PREGUNTAS = DIR / "preguntas.json"
CACHE = DIR / "cache_palabras.json"


def es_relevante(texto: str, evidencia: list[str]) -> bool:
    texto = asistente._sin_tildes(texto).lower()
    return any(re.search(termino, texto) for termino in evidencia)


def palabras_en_cache(pregunta: str, llm, cache: dict) -> str:
    """Las palabras clave del LLM, guardadas por (prompt, pregunta)."""
    version = hashlib.sha1(asistente.PROMPT_PALABRAS_CLAVE.encode("utf-8")).hexdigest()[:10]
    clave = f"{version}|{pregunta}"
    if clave not in cache:
        cache[clave] = asistente.palabras_clave(pregunta, llm)
    return cache[clave]


def medir(ejecutar, preguntas, obtener_palabras, k=5, detalle=False):
    filas = []
    for item in preguntas:
        consulta = obtener_palabras(item["pregunta"])
        fragmentos = asistente.recuperar(ejecutar, consulta, k)
        relevantes = [es_relevante(f["texto"], item["evidencia"]) for f in fragmentos]
        filas.append({
            "pregunta": item["pregunta"],
            "consulta": consulta,
            "precision": sum(relevantes) / len(fragmentos) if fragmentos else 0.0,
            "relevantes": sum(relevantes),
            "devueltos": len(fragmentos),
            "acierto1": bool(relevantes and relevantes[0]),
            "documentos": len({f["paper_id"] for f in fragmentos}),
            "fuentes": [f"{'+' if r else '-'} {f['titulo'][:60]} (p. {f['pagina']})"
                        for f, r in zip(fragmentos, relevantes)],
        })
    resumen = {
        "precision": round(sum(f["relevantes"] for f in filas) / max(1, sum(f["devueltos"] for f in filas)), 3),
        "relevantes": sum(f["relevantes"] for f in filas),
        "devueltos": sum(f["devueltos"] for f in filas),
        "acierto@1": round(sum(f["acierto1"] for f in filas) / len(filas), 3),
        "documentos_distintos": round(sum(f["documentos"] for f in filas) / len(filas), 2),
    }
    if detalle:
        for f in filas:
            print(f"\n{f['precision']:.1f}  {f['pregunta']}\n     consulta: {f['consulta']}")
            for linea in f["fuentes"]:
                print("     " + linea)
    return resumen, filas


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--datos", default="data/app")
    parser.add_argument("--local", action="store_true", help="palabras clave del glosario, sin LLM")
    parser.add_argument("--detalle", action="store_true", help="imprime las fuentes de cada pregunta")
    args = parser.parse_args(argv)

    preguntas = json.loads(PREGUNTAS.read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    llm = None if args.local else asistente.crear_llm()
    motor = Motor(directorio=args.datos, modo_demo=False)
    try:
        if llm is None:
            obtener = asistente.palabras_clave_locales
        else:
            obtener = lambda pregunta: palabras_en_cache(pregunta, llm, cache)  # noqa: E731
        resumen, _ = medir(motor.ejecutar, preguntas, obtener, detalle=args.detalle)
    finally:
        motor.cerrar()
        if llm is not None:
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"modo": "local" if args.local else "llm", **resumen}, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
