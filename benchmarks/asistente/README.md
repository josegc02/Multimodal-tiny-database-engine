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

| Versión | Precisión | Relevantes | Acierto@1 | Clases del tema |
| --- | ---: | ---: | ---: | ---: |
| Con LLM, al inicio: hasta 16 palabras en inglés y español | 0.767 | 69 de 90 | 0.778 | 20 de 35 |
| Con LLM: 5 palabras en inglés, umbral del 60 % (#111) | 0.919 | 79 de 86 | 1.000 | 8 de 8 |
| **Con LLM, ahora: 5 en inglés + cognados, umbral del 70 %** | **0.962** | 76 de 79 | **1.000** | **11 de 12** |
| Sin LLM, al inicio: glosario más las palabras en español | 0.644 | 58 de 90 | 0.611 | — |
| **Sin LLM, ahora: solo las traducidas, umbral del 70 %** | **0.875** | 70 de 80 | 0.833 | — |

Precisión de las citas que escribe el LLM: **0.962** (51 de 53 citas del tema,
ninguna respuesta sin citas). Era 0.943 antes de los cognados. Un prompt de
respuesta más estricto no la mejoró (0.940), así que no se cambió.

### BM25 contra TF-IDF (coseno)

El motor tiene los dos métodos de la Parte 3 (`USING BM25` y `USING TF_IDF`).
Con las mismas palabras clave:

| Umbral | BM25 | TF-IDF coseno |
| --- | ---: | ---: |
| Sin umbral | 0.878 (79/90) | 0.844 (76/90) |
| 60 % | 0.919 (79/86) | 0.852 (75/88) |
| 70 % | 0.949 (75/79) | 0.886 (70/79) |

BM25 gana en todos los casos: la saturación de la frecuencia (k1) evita que un
fragmento que repite un término general le gane a uno que nombra el tema, y la
normalización por largo (b) no castiga a las diapositivas, que son cortas. Se
deja `METODO_RANKING = "BM25"`.

### Qué se probó y qué decidió cada valor

- **Cuántas palabras clave.** Con las 16 que daba el LLM, los términos
  generales (`algorithm`, `memory`, `database`) sumaban puntaje a fragmentos de
  otro tema: en SPIMI, `spimi` quedaba diluido y la precisión era 0.2. Probadas
  3, 4, 5, 6, 7, 8 y 16 sobre las mismas palabras: 3 y 5 quedaron casi iguales
  en precisión (0.856 y 0.844, de 5 fragmentos fijos), y con 5 el primer
  fragmento fue del tema en las 18 preguntas (con 3, en 17).
- **El prompt.** Pedir "solo términos específicos" hizo que el LLM reformulara
  el término de la pregunta (`buffer manager` pasó a `buffer-pool`) y bajó a
  0.851. Pedir que empiece por el término de la pregunta traducido literalmente
  dio 0.919.
- **Las clases del curso, en español.** BM25 compara raíces exactas:
  `fragmentation` (raíz `fragment`) no encuentra `fragmentación`
  (`fragmentacion`), así que con palabras solo en inglés la Clase 12 no salía
  para "fragmentación horizontal". Se probaron cuatro formas de agregar español:
  - todas las palabras de la pregunta en español: 0.633 a 0.644, porque traen
    diapositivas de relleno ("recuperación" trae la clase de recuperación ante
    fallos en una pregunta de RAG);
  - buscar en inglés y en español por separado y fusionar (RRF): 0.633;
  - pedirle al LLM una línea `ES:` con el término en español: 0.895, porque el
    LLM también cambió las palabras en inglés;
  - **cognados de la propia pregunta** (palabras que comparten las primeras 5
    letras con una palabra clave en inglés: fragmentación ~ fragmentation,
    extensible ~ extendible, producto ~ product): **0.962**. Salen de lo que
    escribió el estudiante, no del LLM, no cuestan llamadas y no arrastran
    palabras generales.
- **Umbral relativo.** Descartar los fragmentos bajo el 70 % del puntaje del
  primero: con los cognados sube la precisión de 0.941 (80/85, umbral 60 %) a
  0.962 (76/79). Se pierden 4 fragmentos relevantes a cambio de que el 96 % de
  las fuentes sean del tema, que es lo que se priorizó.

**Límites:** son 18 preguntas y los valores se eligieron sobre ellas, así que
la cifra real con preguntas nuevas puede ser algo menor. La salida del LLM
también varía entre llamadas; la caché fija una de ellas (para medir otra,
borra `cache_palabras.json`).
