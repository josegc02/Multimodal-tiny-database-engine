# Precisión del asistente académico (opción A)

Mide si los fragmentos que recupera `POST /asistente/preguntar` tratan del tema
de la pregunta, y si el LLM cita fragmentos del tema.

## Cómo se mide

`preguntas.json` tiene 18 preguntas en español, como las haría un estudiante:
HNSW, SPIMI, buffer manager, WAL, hashing extensible, fragmentación horizontal,
BM25, R-tree, LSH, IVF, índices aprendidos, RAG, SPLADE, cardinalidad,
LSM-tree, árbol B+, DPR y MongoDB. Cada pregunta trae sus **términos de
evidencia**: un fragmento es relevante si contiene al menos uno (sin tildes ni
mayúsculas). Por ejemplo, para HNSW: `hnsw` o `hierarchical navigable`.

- **Precisión**: fragmentos relevantes / fragmentos devueltos.
- **Relevantes**: cuántos fragmentos relevantes se devolvieron en total, para
  comprobar que la precisión no sube solo por devolver menos.
- **Acierto@1**: preguntas cuyo primer fragmento es relevante.
- **Precisión de citas**: de los fragmentos que el LLM cita, cuántos son
  relevantes.

Es una medida aproximada: un fragmento puede nombrar el término sin explicarlo,
o explicarlo sin nombrarlo. Detecta bien el error que importa: fuentes de otro
tema que comparten palabras generales con la pregunta.

```sh
python -m benchmarks.asistente.precision --local      # glosario, sin LLM
python -m benchmarks.asistente.precision --detalle    # con LLM (BD2_LLM, por defecto Gemini)
python -m benchmarks.asistente.citas                  # precisión de las citas
```

Las palabras clave del LLM se guardan en `cache_palabras.json` por versión del
prompt, así que repetir la medición no gasta cuota. Las citas sí llaman al LLM
cada vez (18 llamadas).

## Resultados (2026-11-19, 259 documentos, 5,714 fragmentos, Gemini 3.1 Flash-Lite)

| Versión | Precisión | Relevantes | Acierto@1 |
| --- | ---: | ---: | ---: |
| Con LLM, antes: hasta 16 palabras en inglés y español | 0.767 | 69 de 90 | 0.778 |
| Con LLM, ahora: 5 palabras en inglés y umbral del 60 % | **0.919** | **79 de 86** | **1.000** |
| Sin LLM, antes: glosario más las palabras en español | 0.644 | 58 de 90 | 0.611 |
| Sin LLM, ahora: solo las traducidas y umbral del 60 % | **0.877** | 71 de 81 | 0.833 |

Precisión de las citas con la recuperación nueva: **0.943** (50 de 53 citas
del tema). Un prompt de respuesta más estricto dio 0.940, así que no se cambió.

Qué se probó y qué decidió cada valor:

- **Cuántas palabras clave.** Con las 16 que daba el LLM, los términos
  generales (`algorithm`, `memory`, `database`) sumaban puntaje a fragmentos de
  otro tema: en SPIMI, `spimi` quedaba diluido y la precisión era 0.2. Probadas
  3, 4, 5, 6, 7, 8 y 16 sobre las mismas palabras: 3 y 5 quedaron casi iguales
  en precisión (0.856 y 0.844, de 5 fragmentos fijos), y con 5 el primer
  fragmento fue del tema en las 18 preguntas (con 3, en 17).
- **Español.** Agregar términos en español traía diapositivas de relleno: 35
  fragmentos de clases, de los que solo 20 eran del tema. Con 5 términos en
  inglés salen 8 y los 8 son del tema, porque las clases usan los términos
  técnicos en inglés. Buscar en inglés y en español por separado y fusionar
  los resultados (RRF) dio 0.633.
- **El prompt.** Pedir "solo términos específicos" hizo que el LLM reformulara
  el término de la pregunta (`buffer manager` pasó a `buffer-pool`) y bajó a
  0.851. Pedir que empiece por el término de la pregunta traducido literalmente
  dio 0.919.
- **Umbral relativo.** Descartar los fragmentos bajo el 60 % del puntaje del
  primero subió la precisión sin perder ningún fragmento relevante; con 70 %
  se empezaba a perder alguno.

**Límites:** son 18 preguntas y los valores se eligieron sobre ellas, así que
la cifra real con preguntas nuevas puede ser algo menor. La salida del LLM
también varía entre llamadas; la caché fija una de ellas.
