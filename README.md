# Minigestor de Base de Datos Multimodal

Proyecto de Base de Datos II (UTEC, 2026-2): un gestor de bases de datos construido desde cero. La **Parte 1 (base de datos relacional)** incluye almacenamiento en disco, índices, SQL, transacciones con control de concurrencia, interfaz gráfica de 4 paneles y comparación experimental. La **Parte 2** implementa geometría, métricas, R-Tree y SQL espacial hasta el issue #23; mapa, datasets y comparación con PostGIS siguen pendientes (#24–#27).

---

## Instalación

Requisitos: **Python 3.12 o superior** (probado con 3.13 en Windows y Ubuntu) y Tkinter (incluido en el instalador oficial de Python para Windows).

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt pytest
```

> En Windows, si `python` apunta a otro intérprete (p. ej. el de MSYS2), usar `py -3.13`.

---

## Ejecución

### Interfaz gráfica (4 paneles)

```bash
python -m frontend.main
```

Paneles: **Archivos** (tablas, esquema, índices y estadísticas), **Consultas** (editor SQL; `Ctrl+Enter` ejecuta), **Resultados** y **Plan de ejecución**. Con `EXPLAIN` o `EXPLAIN ANALYZE`, Resultados muestra el `QUERY PLAN` en texto (como `psql`) y el panel de plan lo muestra como tabla por operador (costo, filas estimadas y reales, tiempos y loops), al estilo de la pestaña *Analysis* de pgAdmin.

> **Modo demo.** Al iniciar, el frontend vacía `demo_data/` (solo los archivos que genera el motor) y crea las tablas de ejemplo `cuentas` y `productos`. Lo creado en una sesión no se conserva al cerrar la aplicación. La capa de almacenamiento sí permite reabrir sus archivos (HeapFile, SequentialFile, B+ y snapshot del hash); los tests de reapertura lo verifican.

**Cargar un CSV desde el frontend.** El botón **Cargar CSV...** del panel de consultas abre el explorador de archivos y escribe en el editor el SQL para cargarlo: un `CREATE TABLE` con los tipos deducidos del archivo (si la tabla todavía no existe) y el `COPY` con el delimitador y la codificación detectados. No ejecuta nada: revisa los tipos y la `PRIMARY KEY` y pulsa **Ejecutar**.

Ejemplo de sesión:

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
--  Planning Time: 0.218 ms
--  Execution Time: 12.887 ms

CREATE TABLE emp (id INT, nombre VARCHAR(20), salario INT) USING BTREE;  -- B+ agrupado
INSERT INTO emp VALUES (1, 'Ana', 3000), (2, 'Bob', 2500), (3, 'Carla', 4100);
CREATE INDEX emp_sal ON emp (salario) USING BTREE;                      -- B+ no agrupado
SELECT nombre FROM emp WHERE salario BETWEEN 2000 AND 3500 ORDER BY salario;
BEGIN TRANSACTION;
DELETE FROM emp WHERE id = 2;
ROLLBACK;
```

### Pruebas

```bash
python -m pytest -q                      # suite completa (también: python -m unittest discover tests)
python -m pytest tests/concurrency -q    # una categoría: storage, indexes, query, concurrency
```

GitHub Actions ejecuta la suite en cada push y pull request sobre Ubuntu y Windows (`.github/workflows/tests.yml`).

### Benchmarks y demostración de concurrencia

```bash
python -m benchmarks.bench_storage       # Heap File vs Archivo Secuencial (1K, 10K, 100K; 3 repeticiones)
python -m benchmarks.bench_indexes       # B+ agrupado vs B+ no agrupado vs Hash extensible
python -m benchmarks.concurrency_demo    # transacciones concurrentes con hilos (enunciado 2.1.4)
```

Resultados, gráficas y metodología: `benchmarks/README.md` y la sección 3 de `docs/informe.md`.

---

## SQL soportado

| Sentencia | Detalle |
| :--- | :--- |
| `CREATE TABLE t (col INT \| FLOAT \| VARCHAR(n) \| POINT, ...) [USING HEAP \| SEQUENTIAL \| BTREE]` | `SEQUENTIAL` y `BTREE` se ordenan por la clave primaria (o la primera columna) y el optimizador usa ese orden para igualdad, rangos y ORDER BY; `BTREE` es una tabla organizada como B+ agrupado (clave única). POINT se almacena como dos doubles. |
| `CREATE INDEX nombre ON t (col) USING HASH \| BTREE \| RTREE` | Índices secundarios: hash extensible, B+ no agrupado o R-Tree sobre POINT. |
| `SELECT [DISTINCT] ... FROM t [JOIN t2 ON ...] [WHERE ...] [GROUP BY ... [HAVING ...]] [ORDER BY ... [ASC\|DESC]] [LIMIT n [OFFSET m]]` | `AND/OR/NOT`, comparaciones, `BETWEEN`, `IN`, `LIKE`, aritmética, `COUNT/SUM/AVG/MIN/MAX` (también con `DISTINCT`). |
| `INSERT INTO t [(cols)] VALUES (...), (...)` | Valida tipos y columnas de todo el lote antes de escribir. |
| `DELETE FROM t [WHERE ...]` | Usa índices si conviene; eliminación lógica en heap y secuencial. |
| `BEGIN [TRANSACTION]`, `END [TRANSACTION]` / `COMMIT`, `ROLLBACK` | Fuera de una transacción cada sentencia es *autocommit*. |
| `CREATE TABLE t (id INT PRIMARY KEY, ...)` o `PRIMARY KEY (id)` | Rechaza claves duplicadas; en un heap crea el índice `t_pkey`. |
| `col INT REFERENCES padre(pk) [ON DELETE RESTRICT \| CASCADE]` o `FOREIGN KEY (col) REFERENCES padre` | Verifica el padre en INSERT/COPY; DELETE del padre falla (RESTRICT) o borra las hijas (CASCADE). Índice automático en la columna hija. |
| `COPY t [(cols)] FROM 'archivo.csv' WITH (FORMAT csv, HEADER true, DELIMITER ';')` | Carga un CSV (comillas, UTF-8 con BOM, `ENCODING 'LATIN1'`); todo o nada, con la línea del error. |
| `EXPLAIN [ANALYZE] SELECT \| INSERT \| DELETE ...` | Plan con el formato de PostgreSQL; `ANALYZE` ejecuta y muestra tiempos y filas reales. |
| `distancia(p, POINT(lat, lon))`, `WITHIN(p, POLYGON((lat, lon), ...))` | Rango, k-NN con ORDER BY/LIMIT y polígonos. SELECT admite `USING HAVERSINE \| EUCLIDEAN`; también se elige métrica como tercer argumento de distancia. |

El optimizador elige por costo estimado entre scan secuencial e índices: hash o B+ para igualdad; B+ para rangos (`<`, `<=`, `>`, `>=`, `BETWEEN`), `ORDER BY` y `GROUP BY`; hash join externo o *index nested loop* para `JOIN`. Gramática completa: `docs/sql_grammar.ebnf`.

En consultas espaciales utiliza un R-Tree vigente cuando el predicado permite
poda; de lo contrario calcula por scan. Ejemplos, contratos y criterios de
los issues #20–#23: [consultas espaciales](docs/consultas_espaciales.md).

---

## Arquitectura

```text
frontend (Tkinter) ──► Motor (fachada)
                          │
            StatementExecutor (sesión: transacción, locks S/IX/SIX/X)
                          │
   lexer ► parser ► AST ► LogicalPlanner ► SQLOptimizer/QueryPlanner ► SQLExecutor
                                                                           │
                         Catalog (tablas, índices, estadísticas, latches)  │
                          │                    │                           │
          storage: HeapFile / SequentialFile / ClusteredBPlusFile    algoritmos externos
          índices: B+ no agrupado / Hash extensible                 (sort k-way, hash group by / join)
          concurrencia: LockManager + TransactionManager (undo log, detección de deadlocks)
```

### Estructura del código

```text
engine/
├── storage/
│   ├── record.py               # Schema de largo fijo y (de)serialización binaria
│   ├── heap_file.py            # Heap File: slotted pages de 4 KB, reutilización de slots, latch por archivo
│   ├── sequential_file.py      # Archivo secuencial: main ordenado + aux, eliminación lazy, reorganización automática
│   └── clustered_file.py       # Tabla organizada como B+ agrupado (CREATE TABLE ... USING BTREE)
├── indexes/
│   ├── bplus_tree.py           # B+ paginado en disco: inserción y eliminación en O(altura)
│   ├── bplus_tree_clustered.py # Hojas con registros completos
│   ├── bplus_tree_unclustered.py # Hojas con (clave, RID); claves duplicadas
│   ├── extendible_hash.py      # Hash extensible en memoria con snapshot JSON
│   └── rtree.py                # Parte 2: R-Tree en disco (rango, k-NN, polígonos)
├── spatial/                    # Parte 2: Point, MBR, Polygon, GeoJSON y métricas Euclidiana/Haversine
├── query/
│   ├── lexer.py, parser.py, ast.py   # Análisis léxico y sintáctico
│   ├── logical_plan.py         # Plan lógico (Scan, Filter, Join, Aggregate, Sort, Project, Limit...)
│   ├── planner.py              # Modelo de costos en páginas (igualdad, rango, orden, group by, join)
│   ├── sql_optimizer.py        # Elige rutas de acceso a partir del plan lógico
│   ├── sql_executor.py         # Ejecución incremental de planes
│   ├── statement_executor.py   # Sesión SQL con transacciones y locks
│   ├── catalog.py              # Tablas, índices (mantenimiento incremental), estadísticas, latches
│   ├── expressions.py          # Evaluación de expresiones
│   └── external_algorithms.py  # External sort k-way, hash group by y hash join externos
└── concurrency/
    ├── lock_manager.py         # Locks IS/IX/S/SIX/X, upgrades y wait-for graph
    ├── transaction.py
    └── transaction_manager.py  # BEGIN/COMMIT/ROLLBACK, undo log robusto
frontend/                       # main.py (ventana), motor.py (fachada), los 4 paneles y panel_mapa.py (Parte 2)
benchmarks/                     # bench_storage, bench_indexes, concurrency_demo, bench_spatial (Parte 2) y results/
datasets/spatial/               # Parte 2: puntos generados y polígonos de distritos
postgis/                        # Parte 2: PostgreSQL + PostGIS (GiST) con Docker
tests/                          # storage, indexes, query (incluye prueba diferencial contra SQLite), concurrency, spatial
docs/                           # informe.md, sql_grammar.ebnf, sql_parser.md, bplus_indexes.md, parte2_espacial.md
```

---

## Documentación

- `docs/informe.md`: informe incremental (diseño, algoritmos, concurrencia y resultados experimentales).
- `docs/sql_parser.md` y `docs/sql_grammar.ebnf`: parser y gramática.
- `docs/bplus_indexes.md`: índices B+.
- `benchmarks/README.md`: metodología de los experimentos.
