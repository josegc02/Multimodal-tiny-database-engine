# API REST del motor

Base de las aplicaciones de la Parte 5. Recibe SQL por HTTP y responde en JSON.

## Levantarla

```bash
python -m pip install -r requirements.txt -r requirements-api.txt
uvicorn api.main:app --reload          # http://127.0.0.1:8000, documentación en /docs
```

| Variable | Para qué | Por defecto |
| :--- | :--- | :--- |
| `BD2_DATA_DIR` | Carpeta de las tablas e índices | `data/app` |
| `BD2_ARCHIVOS` | Carpetas desde las que `/archivos` sirve imágenes y audios (separadas por `;` en Windows y `:` en Linux) | `datasets`, `fotos` y `BD2_DATA_DIR` |
| `BD2_CORS_ORIGINS` | Orígenes del front web, separados por comas | `http://localhost:5173`, `http://127.0.0.1:5173` |
| `BD2_LLM` | LLM de `/asistente/preguntar`: `gemini`, `claude` o `ninguno` | `gemini` |
| `GEMINI_API_KEY` | Key de Gemini (gratis en [aistudio.google.com](https://aistudio.google.com)) | — |
| `ANTHROPIC_API_KEY` | Key de Claude, si `BD2_LLM=claude` (de pago, en platform.claude.com) | — |
| `BD2_LLM_MODELO` | Cambia el modelo del LLM elegido | `gemini-3.1-flash-lite` / `claude-haiku-5-5` |
| `BD2_PALABRAS_CLAVE` | Con `local`, las palabras clave salen del glosario y cada pregunta usa 1 llamada al LLM en vez de 2 | `llm` |
| `BD2_SIN_LLM` | Con `1`, el asistente solo devuelve fragmentos (demo sin internet) | apagado |

Los datos **se conservan entre reinicios**: las tablas se crean una vez (con los scripts de carga) y la API las reabre al iniciar.

## Endpoints

| Método y ruta | Qué hace |
| :--- | :--- |
| `GET /salud` | Comprueba que la API está viva |
| `POST /sql` | Ejecuta SQL |
| `GET /tablas` | Lista las tablas con sus columnas e índices |
| `GET /archivos?ruta=...` | Devuelve una imagen o audio guardado en una columna `IMAGE` / `AUDIO` |
| `POST /asistente/preguntar` | Responde una pregunta con los papers, citando las fuentes (opción A) |
| `GET /asistente/documentos` | La biblioteca: papers y clases con su número de fragmentos |
| `GET /asistente/documentos/{id}` | Un documento con su abstract y sus fragmentos |
| `GET /asistente/documentos/{id}/pdf` | Su PDF, si está en esta máquina (ábralo con `#page=N`) |
| `POST /asistente/documentos` | Sube un PDF: lo fragmenta y lo indexa |

### `POST /sql`

Petición:

```json
{"sql": "SELECT nombre, ubicacion FROM tiendas ORDER BY distancia(ubicacion, POINT(-12.12, -77.03)) LIMIT 1"}
```

Respuesta `200`:

```json
{
  "columnas": ["nombre", "ubicacion"],
  "filas": [["Larcomar", {"lat": -12.1318, "lon": -77.03}]],
  "mensaje": null,
  "plan": null,
  "tiempos": {"planificacion": null, "ejecucion": null}
}
```

- `filas` es una lista de listas, en el orden de `columnas`.
- `POINT` llega como `{"lat", "lon"}`; `IMAGE` y `AUDIO`, como su ruta (úsala con `/archivos`).
- `mensaje` trae el resultado de `CREATE`, `INSERT`, `DELETE` y `COPY` (por ejemplo, `"2 registro(s) insertado(s)"`).
- Con `EXPLAIN [ANALYZE]`, `plan` trae las líneas del plan; con `ANALYZE`, `tiempos` trae los segundos.
- Se pueden enviar varias sentencias separadas por `;`. Se responde con el resultado de la última y los mensajes de todas.

Errores `400`:

```json
{"error": "La tabla 'fantasma' no existe"}
```

**Transacciones.** Cada petición es independiente (autocommit). Un script puede usar `BEGIN ... COMMIT` o `ROLLBACK`, pero si termina con la transacción abierta, o falla a mitad, se deshace todo y se responde con error.

### `GET /tablas`

```json
[
  {
    "nombre": "tiendas",
    "almacenamiento": "heap",
    "filas_estimadas": 2,
    "clave_primaria": "id",
    "columnas": [{"nombre": "id", "tipo": "INT"}, {"nombre": "nombre", "tipo": "VARCHAR(20)"},
                 {"nombre": "ubicacion", "tipo": "POINT"}],
    "indices": [{"nombre": "tiendas_pkey", "columna": "id", "metodo": "hash"},
                {"nombre": "tiendas_geo", "columna": "ubicacion", "metodo": "rtree"}]
  }
]
```

- `almacenamiento`: `heap`, `sequential` o `btree`.
- `metodo`: `hash`, `btree`, `rtree`, `spimi`, `hnsw`, `ivf`, `btree agrupado` o `secuencial`.
- `filas_estimadas` sale de las estadísticas del optimizador; puede ir algo atrasado tras muchas escrituras.

### `GET /archivos?ruta=...`

Devuelve el archivo tal cual. Para mostrar una imagen en el front:

```html
<img src="http://127.0.0.1:8000/archivos?ruta=datasets/tienda/img/123.jpg">
```

Solo sirve imágenes y audios dentro de las carpetas de `BD2_ARCHIVOS`: fuera de ellas responde `403`, y si el archivo no existe, `404`.

### `POST /asistente/preguntar`

Necesita las tablas `papers` y `fragmentos` del corpus (#97): `python -m rag.corpus cargar --datos data/app`. Reinicie la API después de cargar para que vea las tablas.

Para incluir las clases del curso, copie sus PDFs a `datasets/papers/curso/` con un `curso.csv` antes de `rag.corpus construir` (ver `datasets/papers/README.md`). Esa carpeta no se sube al repositorio.

Petición (`k` y `usar_llm` son opcionales):

```json
{"pregunta": "¿Cómo funciona la búsqueda en HNSW?", "k": 5, "usar_llm": true}
```

Respuesta `200`:

```json
{
  "pregunta": "¿Cómo funciona la búsqueda en HNSW?",
  "consulta": "hnsw hierarchical navigable small world graph search",
  "modo": "llm",
  "respuesta": "HNSW organiza los vectores en un grafo por capas [1] y la búsqueda baja de capa en capa [2].",
  "citas": [1, 2],
  "fragmentos": [
    {"n": 1, "id": 812, "paper_id": 14, "titulo": "Efficient and robust approximate nearest neighbor search using HNSW graphs",
     "autores": "Yu. A. Malkov, D. A. Yashunin", "anio": 2016, "url": "https://arxiv.org/abs/1603.09320v4",
     "pagina": 3, "pagina_fin": 4, "puntaje": 12.8431, "texto": "..."}
  ]
}
```

Cómo se arma:

1. La pregunta pasa a **5 palabras clave en inglés** (`consulta`), empezando por el término técnico de la pregunta, porque BM25 compara términos y los papers están en inglés. Las clases del curso también aparecen, porque usan los términos técnicos en inglés (buffer manager, write-ahead log). Con LLM se le pide al modelo; sin LLM, o con `BD2_PALABRAS_CLAVE=local`, se traduce con un glosario pequeño.
2. `SELECT ... FROM fragmentos WHERE MATCH(texto, consulta) USING BM25 ORDER BY puntaje DESC LIMIT 5k`. De esos candidatos se toman los `k` mejores con **a lo más 2 fragmentos por documento**, y se descartan los que no llegan al **60 % del puntaje del primero** (coinciden solo en un término general). Por eso puede haber menos de `k` fuentes. Después, `SELECT ... FROM papers WHERE id IN (...)` trae la metadata, porque el motor no admite `MATCH` con `JOIN`.

Las cifras de precisión que justifican estos valores están en `benchmarks/asistente/README.md`.
3. El LLM recibe los fragmentos numerados y debe responder solo con ellos, citando `[n]`. Si no le sirven, lo dice.

- `[n]` en `respuesta` corresponde a `fragmentos[n-1]`. `citas` lista los números citados, sin repetir y en orden de aparición.
- `modo` es `"sin_llm"` con `usar_llm: false` o `BD2_SIN_LLM=1`. En ese modo `respuesta` es `null` y `citas` es `[]`, y solo se usan los fragmentos.
- Si BM25 no encuentra nada, no se llama al LLM para redactar y `respuesta` lo dice.
- Errores: `400` si falta el corpus o la pregunta está vacía; `422` si `k` no está entre 1 y 20; `502` si falla el LLM (falta la API key, no hay conexión o se alcanzó el límite).

`traza` describe lo que hizo el motor, para mostrarlo en el front:

```json
"traza": {"sql": ["SELECT id, paper_id, ... USING BM25 ...", "SELECT id, titulo, ... WHERE id IN (254, 250)"],
          "ms_motor": 52.3, "documentos": 3, "palabras_con_llm": true, "s_palabras": 0.9,
          "s_redaccion": 2.4, "s_total": 3.4, "modelo": "gemini-3.1-flash-lite"}
```

### Biblioteca y subida

- `GET /asistente/documentos` devuelve `[{"id", "arxiv_id", "titulo", "autores", "anio", "fuente", "url", "tema", "fragmentos"}]`. `fuente` es `arxiv`, `curso` o `subido`.
- `GET /asistente/documentos/{id}` devuelve además `abstract`, `categoria`, `licencia` y `fragmentos` como lista `[{"id", "orden", "pagina", "pagina_fin", "palabras", "texto"}]`. Responde `404` si no existe.
- `GET /asistente/documentos/{id}/pdf` busca el PDF en `datasets/papers/` (o en `BD2_PAPERS_DIR`): `pdf/` para arXiv, `curso/` según `curso.csv` y `subidos/` para los subidos. Responde `404` si no está descargado.
- `POST /asistente/documentos` recibe `multipart/form-data` con `archivo` (PDF de hasta 20 MB), `titulo`, `autores`, `anio` y `tipo` (`paper` o `clase`). Extrae el texto por página, lo corta en fragmentos de 200–500 palabras y lo inserta en `papers` y `fragmentos`; el índice SPIMI se actualiza con el `INSERT`, así que el documento se puede preguntar al instante. Responde `{"id", "paginas", "fragmentos", "palabras", "ms_extraccion", "ms_insercion"}`, o `400` si no es un PDF o no tiene texto extraíble.

## Límites

- Atiende **una petición a la vez**, porque el motor tiene una sola sesión SQL. Alcanza para la demo; una consulta lenta hace esperar a las demás.
- Al iniciar, los índices se reconstruyen desde las tablas. Con miles de imágenes, el HNSW puede tardar alrededor de un minuto en estar listo.
- El asistente tarda lo que tarde el LLM: con `gemini-3.1-flash-lite`, de 3 a 5 segundos por pregunta. Mientras espera al LLM no bloquea las demás peticiones; solo las consultas SQL van de a una.
- **Cuota gratuita de Gemini**: Google la muestra por proyecto en AI Studio y la renueva cada minuto y cada día (a medianoche del Pacífico). Cada pregunta gasta 2 llamadas, o 1 con `BD2_PALABRAS_CLAVE=local`. Si se acaba, el endpoint responde `502` con un mensaje claro; si Google está saturado (`503`), se reintenta solo hasta 3 veces.
- El endpoint de la opción B (`/recomendaciones/{id}`, #101) se agrega sobre esta base.
