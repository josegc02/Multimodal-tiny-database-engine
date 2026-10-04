# Minigestor de Base de Datos Multimodal

Proyecto de Base de Datos II (UTEC, 2026-2): un gestor de bases de datos construido desde cero. La **Parte 1 (base de datos relacional)** está completa: almacenamiento en disco, índices, SQL, transacciones con control de concurrencia, interfaz gráfica de 4 paneles y comparación experimental. Las partes siguientes (espacial, texto, multimedia y aplicación) se apoyan en esta base.

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

Paneles: **Archivos** (tablas, esquema, índices y estadísticas), **Consultas** (editor SQL; `Ctrl+Enter` ejecuta), **Resultados** y **Plan de ejecución**, que muestra el `QUERY PLAN` cuando se ejecuta `EXPLAIN` o `EXPLAIN ANALYZE` (como en `psql`).

> **Modo demo.** Al iniciar, el frontend vacía `demo_data/` (solo los archivos que genera el motor) y crea las tablas de ejemplo `cuentas` y `productos`. Lo creado en una sesión no se conserva al cerrar la aplicación. La capa de almacenamiento sí permite reabrir sus archivos (HeapFile, SequentialFile, B+ y snapshot del hash); los tests de reapertura lo verifican.

Ejemplo de sesión:

```sql
CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(100), carrera_id INT, nota INT);
COPY alumnos FROM 'datos/alumnos.csv' WITH (FORMAT csv, HEADER true);   -- ruta relativa a la raíz del proyecto
EXPLAIN ANALYZE SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id;
--  Sort  (cost=0.00..132.00 rows=333) (actual time=33.554..37.603 rows=355 loops=1)
--    Sort Key: id
--    Sort Method: in-memory (1 run)
--    ->  Seq Scan on alumnos  (cost=0.00..33.00 rows=333) (actual time=0.148..16.519 rows=355 loops=1)
--          Filter: (nota >= 14)
--          Rows Removed by Filter: 645
--  Planning Time: 0.179 ms
--  Execution Time: 38.938 ms

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
| `CREATE TABLE t (col INT \| FLOAT \| VARCHAR(n), ...) [USING HEAP \| SEQUENTIAL \| BTREE]` | `SEQUENTIAL` y `BTREE` se ordenan por la primera columna; `BTREE` es una tabla organizada como B+ agrupado (clave primaria única). |
| `CREATE INDEX nombre ON t (col) USING HASH \| BTREE` | Índices secundarios: hash extensible o B+ no agrupado. |
| `SELECT [DISTINCT] ... FROM t [JOIN t2 ON ...] [WHERE ...] [GROUP BY ... [HAVING ...]] [ORDER BY ... [ASC\|DESC]] [LIMIT n [OFFSET m]]` | `AND/OR/NOT`, comparaciones, `BETWEEN`, `IN`, `LIKE`, aritmética, `COUNT/SUM/AVG/MIN/MAX` (también con `DISTINCT`). |
| `INSERT INTO t [(cols)] VALUES (...), (...)` | Valida tipos y columnas de todo el lote antes de escribir. |
| `DELETE FROM t [WHERE ...]` | Usa índices si conviene; eliminación lógica en heap y secuencial. |
| `BEGIN [TRANSACTION]`, `END [TRANSACTION]` / `COMMIT`, `ROLLBACK` | Fuera de una transacción cada sentencia es *autocommit*. |
| `CREATE TABLE t (id INT PRIMARY KEY, ...)` o `PRIMARY KEY (id)` | Rechaza claves duplicadas; en un heap crea el índice `t_pkey`. |
| `col INT REFERENCES padre(pk) [ON DELETE RESTRICT \| CASCADE]` o `FOREIGN KEY (col) REFERENCES padre` | Verifica el padre en INSERT/COPY; DELETE del padre falla (RESTRICT) o borra las hijas (CASCADE). Índice automático en la columna hija. |
| `COPY t [(cols)] FROM 'archivo.csv' WITH (FORMAT csv, HEADER true, DELIMITER ';')` | Carga un CSV (comillas, UTF-8 con BOM, `ENCODING 'LATIN1'`); todo o nada, con la línea del error. |
| `EXPLAIN [ANALYZE] SELECT \| INSERT \| DELETE ...` | Plan con el formato de PostgreSQL; `ANALYZE` ejecuta y muestra tiempos y filas reales. |

El optimizador elige por costo estimado entre scan secuencial e índices: hash o B+ para igualdad; B+ para rangos (`<`, `<=`, `>`, `>=`, `BETWEEN`), `ORDER BY` y `GROUP BY`; hash join externo o *index nested loop* para `JOIN`. Gramática completa: `docs/sql_grammar.ebnf`.

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
│   └── extendible_hash.py      # Hash extensible en memoria con snapshot JSON
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
frontend/                       # main.py (ventana), motor.py (fachada) y los 4 paneles
benchmarks/                     # bench_storage, bench_indexes, concurrency_demo y results/
tests/                          # storage, indexes, query (incluye prueba diferencial contra SQLite), concurrency
docs/                           # informe.md, sql_grammar.ebnf, sql_parser.md, bplus_indexes.md
```

---

## Documentación

- `docs/informe.md`: informe incremental (diseño, algoritmos, concurrencia y resultados experimentales).
- `docs/sql_parser.md` y `docs/sql_grammar.ebnf`: parser y gramática.
- `docs/bplus_indexes.md`: índices B+.
- `benchmarks/README.md`: metodología de los experimentos.
