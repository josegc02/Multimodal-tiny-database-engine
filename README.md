# Minigestor de Base de Datos Multimodal

Proyecto de Base de Datos II (UTEC, 2026-2): un gestor de bases de datos construido desde cero en Python.

| Parte | Estado | Contenido |
| :--- | :--- | :--- |
| **1. Relacional** | Completa | Heap File, Archivo Secuencial y tabla B+ agrupada; índices B+ y Hash extensible; SQL con optimizador por costos; transacciones con control de concurrencia; interfaz gráfica; comparación experimental. |
| **2. Espacial** | Completa | R-Tree en disco con consultas por radio, k-NN y polígonos; métricas Euclidiana y Haversine; SQL espacial; mapa interactivo (Leaflet); comparación contra GiST de PostGIS. |
| 3–5 | Pendientes | Texto, multimedia y aplicación. |

El diseño, los algoritmos y los resultados experimentales están en el [informe](docs/informe.md).

---

## Manual de instalación

### Requisitos
- **Python 3.12 o superior.** Probado con 3.13 en Windows 11 y Ubuntu.
- **Tkinter**, para la interfaz gráfica. Viene con el instalador oficial de Python en Windows; en Ubuntu: `sudo apt install python3-tk`.
- **Un navegador con Internet**, solo para el mapa (descarga Leaflet y los mapas de OpenStreetMap).
- **Opcional:** Docker, para la comparación con PostgreSQL + PostGIS.

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

---

## Uso

### Interfaz gráfica

```bash
python -m frontend.main
```

| Panel | Contenido |
| :--- | :--- |
| **Archivos** | Tablas, esquema, índices y estadísticas. |
| **Consultas** | Editor SQL (`Ctrl+Enter` ejecuta) y botón **Cargar CSV...**, que genera el `CREATE TABLE` y el `COPY` de un archivo para revisarlos antes de ejecutar. |
| **Resultados** | Filas de la consulta. Con `EXPLAIN` muestra el `QUERY PLAN` en texto, como `psql`. |
| **Plan de ejecución** | Con `EXPLAIN [ANALYZE]`, el mismo plan como tabla por operador: costo, filas estimadas y reales, tiempos y loops. |
| **Mapa** | El botón **Abrir mapa** muestra en el navegador los puntos de la última tabla espacial consultada, con los resultados resaltados y el radio o polígono de la consulta. Un clic en el mapa escribe `POINT(lat, lon)` en el editor. |

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
| `CREATE TABLE t (col INT \| FLOAT \| VARCHAR(n) \| POINT, ...) [USING HEAP \| SEQUENTIAL \| BTREE]` | `SEQUENTIAL` y `BTREE` se ordenan por la clave primaria (o la primera columna); `BTREE` es una tabla organizada como B+ agrupado. `POINT` ocupa 16 bytes. |
| `CREATE INDEX nombre ON t (col) USING HASH \| BTREE \| RTREE` | Hash extensible, B+ no agrupado o R-Tree (solo sobre `POINT`). |
| `SELECT [DISTINCT] ... FROM t [JOIN t2 ON ...] [WHERE ...] [GROUP BY ... [HAVING ...]] [ORDER BY ... [ASC\|DESC]] [LIMIT n [OFFSET m]] [USING HAVERSINE \| EUCLIDEAN]` | `AND/OR/NOT`, comparaciones, `BETWEEN`, `IN`, `LIKE`, aritmética y `COUNT/SUM/AVG/MIN/MAX` (también con `DISTINCT`). |
| `distancia(col, POINT(lat, lon) [, 'euclidean'])`, `WITHIN(col, POLYGON((lat, lon), ...))` | Distancia en metros, en `WHERE` (rango) u `ORDER BY ... LIMIT k` (k-NN), y pertenencia a un polígono. |
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
- **consultas espaciales:** el R-Tree cuando existe.

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
```

Por defecto usan 1.000, 10.000 y 100.000 registros y 3 repeticiones; los resultados y las gráficas se guardan en `benchmarks/results/`. La metodología está en [`benchmarks/README.md`](benchmarks/README.md) y los análisis en las secciones 3 y 5 del informe.

---

## Arquitectura del sistema

```mermaid
flowchart TD
    UI["Frontend Tkinter<br/>(Archivos, Consultas, Resultados, Plan, Mapa)"] --> M["Motor (fachada)"]
    UI -.HTTP local.-> MAP["Mapa Leaflet en el navegador"]
    M --> SE["StatementExecutor<br/>sesión, transacciones y locks"]
    SE --> P["Lexer → Parser → AST"]
    P --> LP["LogicalPlanner"]
    LP --> OPT["SQLOptimizer + QueryPlanner<br/>modelo de costos"]
    OPT --> EX["SQLExecutor"]
    EX --> EXT["Algoritmos externos<br/>sort k-way, hash group by / join"]
    EX --> CAT["Catalog<br/>tablas, índices, estadísticas, latches"]
    CAT --> ST["Almacenamiento<br/>HeapFile · SequentialFile · tabla B+"]
    CAT --> IDX["Índices<br/>B+ · Hash extensible · R-Tree"]
    IDX --> SP["Espacial<br/>Point, MBR, Polygon, Euclidiana, Haversine"]
    SE --> CC["Concurrencia<br/>LockManager + TransactionManager"]
```

Recorrido de una sentencia:
1. El **Motor** recibe el SQL del frontend.
2. El **StatementExecutor** abre la transacción y toma los locks.
3. El SQL se convierte en un **plan lógico**.
4. El **optimizador** elige, con su modelo de costos, la ruta de acceso: recorrer la tabla o usar un índice (B+, hash o R-Tree).
5. El **ejecutor** produce las filas; si los datos no caben en el buffer, usa algoritmos externos.

El **catálogo** mantiene los índices actualizados en cada escritura y las estadísticas que usa el optimizador.

---

## Organización del código fuente

```text
engine/                         # Motor de base de datos (sin dependencias externas)
├── storage/
│   ├── record.py               # Schema de largo fijo (INT, FLOAT, VARCHAR, POINT) y serialización
│   ├── heap_file.py            # Heap File: páginas de 4 KB (slotted pages), reutilización de slots
│   ├── sequential_file.py      # Archivo secuencial: main ordenado + aux, reorganización automática
│   └── clustered_file.py       # Tabla organizada como B+ agrupado
├── indexes/
│   ├── bplus_tree.py           # B+ paginado en disco (inserción y eliminación en O(altura))
│   ├── bplus_tree_clustered.py # Hojas con registros completos
│   ├── bplus_tree_unclustered.py # Hojas con (clave, RID)
│   ├── extendible_hash.py      # Hash extensible con snapshot JSON
│   └── rtree.py                # R-Tree en disco: split cuadrático, rango, k-NN y polígonos
├── spatial/
│   ├── geometry.py             # Point, MBR, Polygon (ray casting) y lectura de GeoJSON
│   └── distance.py             # Euclidiana, Haversine, MINDIST y radio → MBR
├── query/
│   ├── lexer.py, parser.py, ast.py   # Análisis léxico y sintáctico (incluye POINT, POLYGON, distancia, WITHIN)
│   ├── logical_plan.py         # Plan lógico
│   ├── planner.py              # Modelo de costos en páginas
│   ├── sql_optimizer.py        # Rutas de acceso: scan, B+, hash, R-Tree
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
├── panel_*.py                  # Paneles: archivos, consultas, resultados, plan y mapa
├── csv_sql.py                  # SQL sugerido para cargar un CSV
├── mapa.html, mapa_datos.py    # Página Leaflet y datos que publica el mapa
benchmarks/
├── bench_storage.py, bench_indexes.py, complexity.py, concurrency_demo.py   # Parte 1
├── bench_spatial.py, generate_spatial_datasets.py                          # Parte 2
└── results/                    # CSV, metadatos y gráficas de las corridas oficiales
datasets/spatial/               # Polígonos de distritos (GeoJSON) y datos generados (no versionados)
postgis/                        # docker-compose, esquema SQL y cliente de PostGIS
tests/                          # storage, indexes, query, concurrency, spatial y frontend
docs/                           # Informe y documentación técnica
scripts/                        # Automatización de GitHub (etiquetas e issues por avance)
```

Otros archivos:
- **`requirements.txt`:** dependencias (matplotlib, tabulate); `requirements-postgis.txt` agrega psycopg.
- **`scripts/`:** `setup_avance1.*` y `setup_avance2.*` crean las etiquetas, el milestone y los issues de cada avance en GitHub (requieren `gh`). No forman parte del motor.

---

## Documentación

| Archivo | Contenido |
| :--- | :--- |
| [`docs/informe.md`](docs/informe.md) | Informe incremental: arquitectura, dominio de datos, algoritmos y resultados experimentales de las Partes 1 y 2. |
| [`docs/parte2_espacial.md`](docs/parte2_espacial.md) | Diseño de la Parte 2 por issue. |
| [`docs/consultas_espaciales.md`](docs/consultas_espaciales.md) | Contratos de las consultas espaciales (rango, k-NN, polígonos, SQL). |
| [`docs/mapa.md`](docs/mapa.md) | Funcionamiento del mapa. |
| [`docs/sql_parser.md`](docs/sql_parser.md), [`docs/sql_grammar.ebnf`](docs/sql_grammar.ebnf) | Parser y gramática SQL. |
| [`docs/bplus_indexes.md`](docs/bplus_indexes.md) | Índices B+. |
| [`benchmarks/README.md`](benchmarks/README.md) | Cómo correr los experimentos y su metodología. |
