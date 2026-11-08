# Minigestor de Base de Datos Multimodal

Proyecto de Base de Datos II (UTEC, 2026-2): un gestor de bases de datos construido desde cero en Python.

| Parte | Estado | Contenido |
| :--- | :--- | :--- |
| **1. Relacional** | Completa | Heap File, Archivo Secuencial y tabla B+ agrupada; índices B+ y Hash extensible; SQL con optimizador por costos; transacciones con control de concurrencia; interfaz gráfica; comparación experimental. |
| **2. Espacial** | Completa | R-Tree en disco con consultas por radio, k-NN y polígonos; métricas Euclidiana y Haversine; SQL espacial; mapa interactivo (tkintermapview); comparación contra GiST de PostGIS. |
| **3. Texto** | Completa | Preprocesamiento (stopwords y stemming en español e inglés), índice invertido SPIMI en disco, rankings TF-IDF + coseno y BM25, SQL con `MATCH ... USING TF_IDF \| BM25` y `SCORE()`; comparación contra GIN de PostgreSQL. |
| **4. Multimedia** | Completa (experimento con BoVW por actualizar) | ExtractFeatures con Bag of Visual/Audio Words (SIFT → K-Means K=1024 para imágenes, MFCC → K=256 para audio → TF-IDF); índices IVF y HNSW; métricas euclidiana, producto punto y coseno; SQL con `SIMILAR_TO` y `SIMILARITY_SCORE()`; galería en la interfaz; comparación IVF vs HNSW. |
| 5. Aplicación de IA | Pendiente | Entrega final. |

El diseño, los algoritmos y los resultados experimentales están en el [informe](docs/informe.md).

> **Nota sobre la comparación experimental de la Parte 4.** Los resultados publicados en
> [`benchmarks/results/multimedia/`](benchmarks/results/multimedia/report.md) (1K, 10K y 100K imágenes de
> MS-COCO, IVF vs HNSW, euclidiana vs coseno) se midieron **antes** de integrar Bag of Visual Words, con un
> descriptor global: el promedio de los descriptores SIFT (128 dimensiones). Son mediciones válidas de los
> índices sobre ese vector, pero no sobre el vector final de ExtractFeatures (histograma BoVW de 256
> dimensiones). Por falta de tiempo para repetir la corrida completa (~2 h) antes de este avance, se presentan
> esos resultados. Qué cambia en teoría con BoVW:
> - **Tiempos y memoria:** la misma tendencia, con valores mayores (el costo de cada distancia es O(d) y d pasa de 128 a 256).
> - **Recall@10:** más bajo con los mismos parámetros, porque en más dimensiones las distancias se concentran.
>   En una prueba con 500 imágenes de `coco1k`, IVF pasó de 0,99 a 0,87 y HNSW de 0,998 a 0,97.
> - **Euclidiana vs coseno:** los vectores BoVW tienen norma 1, y entonces ‖a − b‖² = 2 − 2·cos(a, b):
>   ambas métricas dan el mismo ranking de vecinos.
>
> El benchmark ya usa BoVW por defecto (`--features bovw`; `--features sift-mean` reproduce la tabla publicada)
> y la corrida completa se actualizará en la entrega final. Detalles en la sección 11 del informe.

---

## Manual de instalación

### Requisitos
- **Python 3.12 o superior.** Probado con 3.13 en Windows 11 y Ubuntu.
- **Tkinter**, para la interfaz gráfica. Viene con el instalador oficial de Python en Windows; en Ubuntu: `sudo apt install python3-tk`.
- **Internet**, solo para el fondo del mapa (el panel descarga los mosaicos; los datos son locales).
- **OpenCV y librosa** (en `requirements.txt`), para extraer los vectores de las columnas `IMAGE` y `AUDIO`.
- **Opcional:** Docker, para las comparaciones con PostgreSQL (PostGIS en la Parte 2 y GIN en la Parte 3).

### Instalación básica

```bash
git clone https://github.com/josegc02/Multimodal-tiny-database-engine.git
cd Multimodal-tiny-database-engine
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt pytest
```

> En Windows, si `python` apunta a otro intérprete (por ejemplo, el de MSYS2), usar `py -3.13`.

### PostgreSQL + PostGIS (opcional, solo para el benchmark espacial)

```bash
python -m pip install -r requirements-postgis.txt           # psycopg
docker compose -f postgis/docker-compose.yml up -d           # puerto 5433, usuario/clave bd2/bd2, base "espacial"
# Si el puerto 5433 está ocupado:
#   POSTGIS_PORT=5434 docker compose -f postgis/docker-compose.yml up -d
docker compose -f postgis/docker-compose.yml down            # detener (con -v también borra los datos)
```

Detalles en [`postgis/README.md`](postgis/README.md).

### PostgreSQL + GIN (opcional, solo para el benchmark de texto)

```bash
python -m pip install -r requirements-text-postgres.txt     # psycopg
docker compose -f postgres_text/docker-compose.yml up -d --wait
docker compose -f postgres_text/docker-compose.yml down
```

Detalles en [`postgres_text/README.md`](postgres_text/README.md).

---

## Uso

### Interfaz gráfica

```bash
python -m frontend.main
```

El panel permite elegir un archivo multimedia para insertar una consulta
`SIMILAR_TO` de ejemplo. Los resultados que proyectan una ruta de imagen o
audio se muestran en galería; para incluir su puntuación, selecciona también
`SIMILARITY_SCORE() AS score`. El botón de audio abre el archivo con el
reproductor predeterminado del sistema. En consultas `MATCH`, se agrega un
fragmento visual si la columna de texto buscada está en la selección; usa
`SCORE() AS relevancia` para mostrar su puntuación.

La barra del editor incluye **Tema claro / Tema oscuro** para alternar la
apariencia sin perder la consulta ni los resultados. La aplicación inicia en
tema oscuro; la elección dura hasta cerrar la ventana.

| Panel | Contenido |
| :--- | :--- |
| **Archivos** | Tablas, esquema, índices y estadísticas. |
| **Consultas** | Editor SQL (`Ctrl+Enter` ejecuta) y botón **Cargar CSV...**, que genera el `CREATE TABLE` y el `COPY` de un archivo para revisarlos antes de ejecutar. |
| **Resultados** | Filas de la consulta. Con `EXPLAIN` muestra el `QUERY PLAN` en texto, como `psql`. |
| **Plan de ejecución** | Con `EXPLAIN [ANALYZE]`, el mismo plan como tabla por operador: costo, filas estimadas y reales, tiempos y loops. |
| **Mapa** | La pestaña **Mapa** muestra los puntos de la última tabla espacial consultada, con los resultados resaltados y el radio o polígono de la consulta. El clic derecho > **Insertar POINT aquí** escribe `POINT(lat, lon)` en el editor. |

> **Modo demo.** Al iniciar, el frontend vacía `demo_data/` (solo los archivos que genera el motor) y crea las tablas de ejemplo `cuentas` y `productos`. Lo creado en una sesión no se conserva al cerrar la aplicación. La capa de almacenamiento sí puede reabrir sus archivos; los tests de reapertura lo verifican.

### Ejemplo relacional

```sql
CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(100), carrera_id INT, nota INT);
COPY alumnos FROM 'datos/alumnos.csv' WITH (FORMAT csv, HEADER true);   -- ruta relativa a la raíz del proyecto
EXPLAIN ANALYZE SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id;
--  Sort  (cost=132.00..132.00 rows=333) (actual time=11.810..11.909 rows=324 loops=1)
--    Sort Key: id
--    Sort Method: in-memory
--    ->  Seq Scan on alumnos  (cost=0.00..33.00 rows=333) (actual time=0.136..10.349 rows=324 loops=1)
--          Filter: (nota >= 14)
--          Rows Removed by Filter: 676

CREATE TABLE emp (id INT, nombre VARCHAR(20), salario INT) USING BTREE;  -- B+ agrupado
CREATE INDEX emp_sal ON emp (salario) USING BTREE;                      -- B+ no agrupado
BEGIN TRANSACTION;
DELETE FROM emp WHERE id = 2;
ROLLBACK;
```

### Ejemplo de texto

```sql
CREATE TABLE articulos (id INT PRIMARY KEY, titulo VARCHAR(100), texto TEXT);
CREATE INDEX articulos_texto ON articulos (texto) USING SPIMI;           -- WITH (LANGUAGE = 'en') para inglés
INSERT INTO articulos VALUES (1, 'Índices', 'Un índice invertido acelera la búsqueda de texto');
SELECT id, titulo, SCORE() AS relevancia FROM articulos
WHERE MATCH(texto, 'índice de búsqueda') USING BM25
ORDER BY relevancia DESC LIMIT 10;
```

### Ejemplo multimedia

```sql
CREATE TABLE imagenes (id INT PRIMARY KEY, nombre VARCHAR(30), foto IMAGE);
CREATE INDEX imagenes_foto ON imagenes (foto) USING HNSW WITH (METRIC = cosine);
-- Al insertar se guarda la ruta y se extrae el vector Bag of Words (SIFT para IMAGE, MFCC para AUDIO)
INSERT INTO imagenes VALUES (1, 'gato', 'fotos/gato.jpg'), (2, 'perro', 'fotos/perro.jpg');
SELECT nombre, SIMILARITY_SCORE() AS score FROM imagenes
WHERE SIMILAR_TO('fotos/consulta.jpg', k=10) USING HNSW WITH METRIC=cosine
ORDER BY score DESC;

CREATE TABLE canciones (id INT, nombre VARCHAR(30), audio AUDIO);
CREATE INDEX canciones_audio ON canciones (audio) USING IVF;                 -- METRIC euclidean por defecto
SELECT * FROM canciones WHERE SIMILAR_TO('audio_query.wav', k=5) USING IVF;
```

El vector de cada archivo es su histograma Bag of Visual/Audio Words con TF-IDF, calculado con los vocabularios de `models/`: K = 1024 palabras sobre descriptores SIFT para imágenes y K = 256 sobre MFCC para audio. Para volver a entrenarlos (el de imágenes tarda ~8 min):

```bash
python scripts/download_bow_training_data.py            # 500 imágenes de coco1k y 200 clips de ESC-50 (~160 MB)
python scripts/train_codebook.py --kind image --input datasets/bow_training/coco --sample 200000
python scripts/train_codebook.py --kind audio --input datasets/bow_training/esc50
```

Los clips de audio son de ESC-50 (K. J. Piczak, *ESC: Dataset for Environmental Sound Classification*, 2015), con licencia CC BY-NC 3.0.

### Ejemplo espacial

```sql
CREATE TABLE tiendas (id INT PRIMARY KEY, nombre VARCHAR(30), ubicacion POINT);
INSERT INTO tiendas VALUES (1, 'Centro', POINT(-12.0464, -77.0428)),
                           (2, 'Miraflores', POINT(-12.1211, -77.0297)),
                           (3, 'Callao', POINT(-12.0566, -77.1181));
CREATE INDEX tiendas_geo ON tiendas (ubicacion) USING RTREE;

-- Rango: tiendas a menos de 5 km (en metros, Haversine por defecto)
SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;

-- k-NN: las 2 más cercanas, con la métrica Euclidiana
SELECT * FROM tiendas ORDER BY distancia(ubicacion, POINT(-12.05, -77.04)) LIMIT 2 USING EUCLIDEAN;

-- Polígono: tiendas dentro de una zona (vértices lat, lon; el borde cuenta como dentro)
SELECT * FROM tiendas WHERE WITHIN(ubicacion, POLYGON((-12.15, -77.10), (-12.00, -77.10), (-12.00, -77.00), (-12.15, -77.00)));

EXPLAIN ANALYZE SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;
--  R-Tree Radius Scan using tiendas_geo on tiendas ... (Nodes Visited, Exact Refinements)
```

Para cargar el dataset de la comparación experimental en la interfaz, genera los archivos y ejecuta el SQL de carga que se crea:

```bash
python -m benchmarks.generate_spatial_datasets --sizes 1000
```

El archivo es `datasets/spatial/generated/cargar_motor_1000.sql`.

### SQL soportado

| Sentencia | Detalle |
| :--- | :--- |
| `CREATE TABLE t (col INT \| FLOAT \| VARCHAR(n) \| POINT \| TEXT \| IMAGE \| AUDIO, ...) [USING HEAP \| SEQUENTIAL \| BTREE]` | `SEQUENTIAL` y `BTREE` se ordenan por la clave primaria (o la primera columna); `BTREE` es una tabla organizada como B+ agrupado. `POINT` ocupa 16 bytes. `IMAGE` y `AUDIO` guardan la ruta del archivo y su vector. |
| `CREATE INDEX nombre ON t (col) USING HASH \| BTREE \| RTREE \| SPIMI \| HNSW \| IVF [WITH (...)]` | Hash extensible, B+ no agrupado, R-Tree (solo `POINT`), SPIMI (`TEXT`/`VARCHAR`, `WITH (LANGUAGE = 'en')`) o HNSW/IVF (`IMAGE`/`AUDIO`, `WITH (METRIC = euclidean \| cosine \| dot)`). |
| `SELECT [DISTINCT] ... FROM t [JOIN t2 ON ...] [WHERE ...] [GROUP BY ... [HAVING ...]] [ORDER BY ... [ASC\|DESC]] [LIMIT n [OFFSET m]] [USING HAVERSINE \| EUCLIDEAN]` | `AND/OR/NOT`, comparaciones, `BETWEEN`, `IN`, `LIKE`, aritmética y `COUNT/SUM/AVG/MIN/MAX` (también con `DISTINCT`). |
| `distancia(col, POINT(lat, lon) [, 'euclidean'])`, `WITHIN(col, POLYGON((lat, lon), ...))` | Distancia en metros, en `WHERE` (rango) u `ORDER BY ... LIMIT k` (k-NN), y pertenencia a un polígono. |
| `MATCH(col, 'consulta') USING TF_IDF \| BM25`, `SCORE()` | Búsqueda de texto con un índice SPIMI, en el `WHERE`; `SCORE()` es la relevancia. |
| `SIMILAR_TO([col,] 'archivo', k=N) USING HNSW \| IVF [WITH METRIC=euclidean \| cosine \| dot]`, `SIMILARITY_SCORE()` | Los k vecinos más similares al archivo, en el `WHERE`. `SIMILARITY_SCORE()` crece con la similitud: coseno, producto punto o `1 / (1 + distancia euclidiana)`. |
| `INSERT INTO t [(cols)] VALUES (...), (...)` | Valida tipos y columnas de todo el lote antes de escribir. |
| `DELETE FROM t [WHERE ...]` | Usa índices si conviene. |
| `BEGIN [TRANSACTION]`, `COMMIT` / `END`, `ROLLBACK` | Fuera de una transacción cada sentencia es *autocommit*. |
| `PRIMARY KEY`, `REFERENCES padre(pk) [ON DELETE RESTRICT \| CASCADE]` | Claves primarias e índice automático `t_pkey`; llaves foráneas con su índice. |
| `COPY t [(cols)] FROM 'archivo.csv' WITH (FORMAT csv, HEADER true, DELIMITER ';')` | Carga un CSV completo o nada, e indica la línea del error. |
| `EXPLAIN [ANALYZE] SELECT \| INSERT \| DELETE ...` | Plan con el formato de PostgreSQL; `ANALYZE` ejecuta y muestra tiempos y filas reales. |

El optimizador elige por costo estimado entre recorrer la tabla y usar un índice:
- **igualdad:** hash o B+;
- **rangos, `ORDER BY` y `GROUP BY`:** B+;
- **JOIN:** hash join externo o *index nested loop*;
- **consultas espaciales:** el R-Tree cuando existe;
- **`MATCH` y `SIMILAR_TO`:** siempre su índice SPIMI, HNSW o IVF.

Gramática completa: [`docs/sql_grammar.ebnf`](docs/sql_grammar.ebnf).

### Pruebas

```bash
python -m pytest -q                      # suite completa (también: python -m unittest discover tests)
python -m pytest tests/spatial -q        # una carpeta: storage, indexes, query, concurrency, spatial
BD2_POSTGIS_DSN=postgresql://bd2:bd2@localhost:5433/espacial python -m pytest tests/spatial -q   # + prueba contra PostGIS
```

GitHub Actions ejecuta la suite en cada push y pull request sobre Ubuntu y Windows (`.github/workflows/tests.yml`).

### Benchmarks

```bash
python -m benchmarks.bench_storage       # Parte 1: Heap File vs Archivo Secuencial
python -m benchmarks.bench_indexes       # Parte 1: B+ agrupado vs B+ no agrupado vs Hash extensible
python -m benchmarks.concurrency_demo    # Parte 1: transacciones concurrentes con hilos
python -m benchmarks.bench_spatial       # Parte 2: Secuencial vs R-Tree vs GiST (requiere PostGIS)
python -m benchmarks.bench_spatial --sin-postgis   # Parte 2 sin PostgreSQL (GiST queda como NA)

python -m benchmarks.generate_text_datasets         # Parte 3: corpus de noticias de 1K, 10K y 100K documentos
python -m benchmarks.bench_text                     # Parte 3: TF-IDF vs BM25 vs GIN (requiere PostgreSQL GIN)

# Parte 4: IVF vs HNSW sobre MS-COCO (requiere los subconjuntos de scripts/download_coco.py,
# create_subsets.py y generate_queries.py); ~2 h para 1K, 10K y 100K
python -m benchmarks.multimedia_compare --dataset-dir datasets/coco_subsets --output benchmarks/results/smoke/multimedia
```

Por defecto usan 1.000, 10.000 y 100.000 registros; los resultados y las gráficas se guardan en `benchmarks/results/`. La metodología está en [`benchmarks/README.md`](benchmarks/README.md), [`benchmarks/TEXT_BENCHMARK.md`](benchmarks/TEXT_BENCHMARK.md) y [`benchmarks/MULTIMEDIA_BENCHMARK.md`](benchmarks/MULTIMEDIA_BENCHMARK.md), y los análisis en las secciones 3, 5, 9 y 11 del informe.

---

## Arquitectura del sistema

```mermaid
flowchart TD
    UI["Frontend Tkinter<br/>(Archivos, Consultas, Resultados, Plan, Mapa)"] --> M["Motor (fachada)"]
    M --> SE["StatementExecutor<br/>sesión, transacciones y locks"]
    SE --> P["Lexer → Parser → AST"]
    P --> LP["LogicalPlanner"]
    LP --> OPT["SQLOptimizer + QueryPlanner<br/>modelo de costos"]
    OPT --> EX["SQLExecutor"]
    EX --> EXT["Algoritmos externos<br/>sort k-way, hash group by / join"]
    EX --> CAT["Catalog<br/>tablas, índices, estadísticas, latches"]
    CAT --> ST["Almacenamiento<br/>HeapFile · SequentialFile · tabla B+"]
    CAT --> IDX["Índices<br/>B+ · Hash extensible · R-Tree · SPIMI · HNSW · IVF"]
    IDX --> SP["Espacial<br/>Point, MBR, Polygon, Euclidiana, Haversine"]
    IDX --> TX["Texto<br/>tokens, stopwords, stemming; TF-IDF y BM25"]
    ST --> FE["ExtractFeatures<br/>SIFT / MFCC → Bag of Words (K-Means) → TF-IDF"]
    IDX --> VE["Vectores<br/>euclidiana, producto punto, coseno"]
    SE --> CC["Concurrencia<br/>LockManager + TransactionManager"]
```

Recorrido de una sentencia:
1. El **Motor** recibe el SQL del frontend.
2. El **StatementExecutor** abre la transacción y toma los locks.
3. El SQL se convierte en un **plan lógico**.
4. El **optimizador** elige, con su modelo de costos, la ruta de acceso: recorrer la tabla o usar un índice (B+, hash o R-Tree). `MATCH` usa siempre su índice SPIMI y `SIMILAR_TO` su índice HNSW o IVF.
5. El **ejecutor** produce las filas; si los datos no caben en el buffer, usa algoritmos externos.

El **catálogo** mantiene los índices actualizados en cada escritura y las estadísticas que usa el optimizador.

---

## Organización del código fuente

```text
engine/                         # Motor de base de datos (sin dependencias externas)
├── storage/
│   ├── record.py               # Schema de largo fijo (INT, FLOAT, VARCHAR, POINT, TEXT, IMAGE, AUDIO)
│   ├── text_store.py           # Valores TEXT fuera de la página del registro
│   ├── media_store.py          # Ruta y vector de cada valor IMAGE / AUDIO
│   ├── heap_file.py            # Heap File: páginas de 4 KB (slotted pages), reutilización de slots
│   ├── sequential_file.py      # Archivo secuencial: main ordenado + aux, reorganización automática
│   └── clustered_file.py       # Tabla organizada como B+ agrupado
├── indexes/
│   ├── bplus_tree.py           # B+ paginado en disco (inserción y eliminación en O(altura))
│   ├── bplus_tree_clustered.py # Hojas con registros completos
│   ├── bplus_tree_unclustered.py # Hojas con (clave, RID)
│   ├── extendible_hash.py      # Hash extensible con snapshot JSON
│   ├── rtree.py                # R-Tree en disco: split cuadrático, rango, k-NN y polígonos
│   ├── spimi.py                # Índice invertido SPIMI en disco; rankings TF-IDF + coseno y BM25
│   ├── ivf.py, hnsw.py         # Índices vectoriales aproximados
│   └── vector_index.py         # Adapta IVF y HNSW al catálogo (columnas IMAGE / AUDIO)
├── text/
│   └── preprocessing.py        # Tokenización, stopwords (es/en) y stemming Snowball
├── features/
│   ├── image/sift.py, audio/mfcc.py   # Descriptores locales
│   ├── kmeans.py, bow.py       # K-Means y Bag of Visual/Audio Words con TF-IDF
│   └── registry.py             # ExtractFeatures: el vector de cada IMAGE / AUDIO
├── vector/
│   └── metrics.py              # Euclidiana, producto punto y coseno
├── spatial/
│   ├── geometry.py             # Point, MBR, Polygon (ray casting) y lectura de GeoJSON
│   └── distance.py             # Euclidiana, Haversine, MINDIST y radio → MBR
├── query/
│   ├── lexer.py, parser.py, ast.py   # Análisis léxico y sintáctico (POINT, POLYGON, MATCH, SIMILAR_TO, ...)
│   ├── logical_plan.py         # Plan lógico
│   ├── planner.py              # Modelo de costos en páginas
│   ├── sql_optimizer.py        # Rutas de acceso: scan, B+, hash, R-Tree, texto y vectores
│   ├── sql_executor.py         # Ejecución incremental de planes
│   ├── statement_executor.py   # Sesión SQL: transacciones, locks, COPY, EXPLAIN
│   ├── explain.py              # EXPLAIN [ANALYZE] con el formato de PostgreSQL
│   ├── catalog.py              # Tablas, índices, estadísticas y latches
│   ├── expressions.py          # Evaluación de expresiones (incluye las espaciales)
│   └── external_algorithms.py  # External sort k-way, hash group by y hash join
└── concurrency/
    ├── lock_manager.py         # Locks IS/IX/S/SIX/X y detección de deadlocks
    ├── transaction.py
    └── transaction_manager.py  # BEGIN/COMMIT/ROLLBACK con undo log
frontend/
├── main.py                     # Ventana principal
├── motor.py                    # Fachada entre la interfaz y el motor
├── panel_*.py                  # Paneles: archivos, consultas, resultados (con galería), plan y mapa
├── tema.py, sql_highlight.py   # Tema claro/oscuro y resaltado de SQL
├── csv_sql.py                  # SQL sugerido para cargar un CSV
├── mapa_datos.py               # Datos que recibe el panel de mapa
benchmarks/
├── bench_storage.py, bench_indexes.py, complexity.py, concurrency_demo.py   # Parte 1
├── bench_spatial.py, generate_spatial_datasets.py                          # Parte 2
├── bench_text.py, generate_text_datasets.py, text_*.py                     # Parte 3
├── multimedia_*.py                                                         # Parte 4
└── results/                    # CSV, metadatos y gráficas de las corridas oficiales
models/                         # Vocabularios Bag of Words (imagen K=1024, audio K=256)
datasets/                       # Distritos (GeoJSON) y descripción del corpus de texto; lo generado no se versiona
postgis/                        # docker-compose, esquema SQL y cliente de PostGIS
postgres_text/                  # docker-compose y cliente de PostgreSQL con índice GIN
tests/                          # storage, indexes, query, concurrency, spatial, text, features y frontend
docs/                           # Informe y documentación técnica
scripts/                        # Datasets COCO, entrenamiento de vocabularios y automatización de GitHub
```

Otros archivos:
- **`requirements.txt`:** dependencias (numpy, matplotlib, tabulate, ttkbootstrap, tkintermapview, snowballstemmer, opencv-python, librosa); `requirements-postgis.txt` y `requirements-text-postgres.txt` agregan psycopg.
- **`scripts/`:** `download_coco.py`, `create_subsets.py` y `generate_queries.py` preparan los subconjuntos de MS-COCO; `download_bow_training_data.py` y `train_codebook.py` regeneran los vocabularios de `models/`. Los `setup_avance*` crean etiquetas e issues en GitHub (requieren `gh`).

---

## Documentación

| Archivo | Contenido |
| :--- | :--- |
| [`docs/informe.md`](docs/informe.md) | Informe incremental: arquitectura, dominio de datos, algoritmos y resultados experimentales de las Partes 1 a 4. |
| [`docs/parte2_espacial.md`](docs/parte2_espacial.md) | Diseño de la Parte 2 por issue. |
| [`docs/consultas_espaciales.md`](docs/consultas_espaciales.md) | Contratos de las consultas espaciales (rango, k-NN, polígonos, SQL). |
| [`docs/mapa.md`](docs/mapa.md) | Funcionamiento del mapa. |
| [`docs/sql_parser.md`](docs/sql_parser.md), [`docs/sql_grammar.ebnf`](docs/sql_grammar.ebnf) | Parser y gramática SQL. |
| [`docs/bplus_indexes.md`](docs/bplus_indexes.md) | Índices B+. |
| [`benchmarks/README.md`](benchmarks/README.md) | Cómo correr los experimentos y su metodología. |
| [`benchmarks/TEXT_BENCHMARK.md`](benchmarks/TEXT_BENCHMARK.md), [`datasets/text/README.md`](datasets/text/README.md) | Benchmark y corpus de la Parte 3. |
| [`postgres_text/README.md`](postgres_text/README.md) | PostgreSQL con GIN para la comparación de texto. |
| [`benchmarks/MULTIMEDIA_BENCHMARK.md`](benchmarks/MULTIMEDIA_BENCHMARK.md) | Benchmark multimedia y cómo repetirlo con BoVW. |
