"""Precisión de las citas del asistente (#98): ¿el LLM cita fragmentos del tema?

Para cada pregunta de ``preguntas.json`` se recuperan los fragmentos como en el
endpoint, el LLM redacta la respuesta con ``PROMPT_RESPUESTA`` y se mide:

- precisión de citas: de los fragmentos citados, cuántos contienen un término
  de evidencia de la pregunta;
- citas a fragmentos fuera de tema, en total;
- respuestas sin ninguna cita.

Uso, desde la raíz y con el corpus en ``data/app`` (gasta 2 llamadas al LLM por
pregunta la primera vez; las palabras clave salen de ``cache_palabras.json``)::

    python -m benchmarks.asistente.citas
"""

from __future__ import annotations

import json
import sys
import time

from api import asistente
from benchmarks.asistente import precision as P
from frontend.motor import Motor


def medir_citas(ejecutar, preguntas, llm, prompt, obtener_palabras, pausa=4.0):
    citadas = relevantes = sin_citas = 0
    for item in preguntas:
        fragmentos = asistente.recuperar(ejecutar, obtener_palabras(item["pregunta"]), 5)
        if not fragmentos:
            continue
        texto = llm.completar(prompt, asistente.mensaje_respuesta(item["pregunta"], fragmentos), 16000)
        numeros = asistente.citas(texto, len(fragmentos))
        sin_citas += not numeros
        for n in numeros:
            citadas += 1
            relevantes += P.es_relevante(fragmentos[n - 1]["texto"], item["evidencia"])
        time.sleep(pausa)
    return {"precision_citas": round(relevantes / max(1, citadas), 3), "citadas": citadas,
            "fuera_de_tema": citadas - relevantes, "respuestas_sin_cita": sin_citas}


def main():
    preguntas = json.loads(P.PREGUNTAS.read_text(encoding="utf-8"))
    cache = json.loads(P.CACHE.read_text(encoding="utf-8")) if P.CACHE.exists() else {}
    llm = asistente.crear_llm()
    motor = Motor(directorio="data/app", modo_demo=False)
    try:
        resultado = medir_citas(motor.ejecutar, preguntas, llm, asistente.PROMPT_RESPUESTA,
                                lambda q: P.palabras_en_cache(q, llm, cache))
    finally:
        motor.cerrar()
        P.CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
