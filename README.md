# Motor de Base de Datos Relacional — Avance 1

Proyecto de Base de Datos II para la implementación de un motor de base de datos relacional y multimodal desde cero.

---

## Estructura del proyecto — Avance 1 (Parte 1: Base de Datos Relacional)

```text
minigestor-bd/
├── README.md                       # este archivo: arquitectura, instalación, uso
├── requirements.txt                 # dependencias Python del proyecto
├── .gitignore                       # __pycache__/, *.heap, *.db, venv/, results/
├── setup_avance1.ps1                # automatización de labels/milestone/issues (PowerShell)
├── setup_avance1.sh                 # automatización de labels/milestone/issues (Bash)
│
├── engine/                          # motor de base de datos (código fuente principal)
│   ├── __init__.py
│   │
│   ├── storage/                     # Gestión de archivos y almacenamiento en disco
│   │   ├── __init__.py
│   │   ├── heap_file.py             # Heap File: páginas slotted (4KB), reutilización de espacio
│   │   ├── sequential_file.py       # Archivo Secuencial Paginado: orden físico, área aux y reorganización
│   │   └── record.py                # Schema y (de)serialización binaria de registros
│   │
│   ├── indexes/                     # Estructuras de indexación
│   │   ├── __init__.py
│   │   ├── bplus_tree.py            # Árbol B+ genérico / estructura base en disco
│   │   ├── bplus_tree_clustered.py  # Índice B+ agrupado (clustered, registros en hojas)
│   │   ├── bplus_tree_unclustered.py# Índice B+ no agrupado (unclustered, punteros a RID)
│   │   └── extendible_hash.py       # Índice Hash Dinámico (Extendible Hashing con directorio y buckets)
│   │
│   ├── query/                       # Procesamiento y ejecución de consultas SQL
│   │   ├── __init__.py
│   │   ├── lexer.py                 # Tokenizador léxico de sentencias SQL
│   │   ├── parser.py                # Parser sintáctico (SELECT, INSERT, DELETE, transacciones)
│   │   ├── ast.py                   # Nodos del árbol de sintaxis abstracta (AST)
│   │   ├── expressions.py           # Expresiones aritméticas, booleanas y predicados (WHERE)
│   │   ├── logical_plan.py          # Definición de operadores del plan lógico (Scan, Filter, Project, etc.)
│   │   ├── catalog.py               # Catálogo de metadatos de tablas, esquemas e índices
│   │   ├── planner.py               # Generación y selección de planes de ejecución
│   │   ├── sql_optimizer.py         # Optimizador lógico y selección de rutas de acceso por índice
│   │   ├── executor.py              # Ejecutor base de operaciones relacionales
│   │   ├── sql_executor.py          # Ejecución de planes de consulta SELECT
│   │   ├── statement_executor.py    # Ejecución de sentencias DML (INSERT, DELETE) y control de transacciones
│   │   ├── external_algorithms.py   # External Sort (ORDER BY) y External Hash (GROUP BY/JOIN)
│   │   ├── _temp_records.py         # Manejo de registros temporales para algoritmos externos
│   │   └── errors.py                # Jerarquía de excepciones de parseo y ejecución
│   │
│   └── concurrency/                 # Transacciones y control de concurrencia
│       ├── __init__.py
│       ├── lock_manager.py          # Administrador de locks compartidos y exclusivos (2PL estricto)
│       ├── transaction.py           # Contexto de transacción y estado transaccional
│       └── transaction_manager.py   # Coordinador del ciclo de vida transaccional (BEGIN/COMMIT/ABORT)
│
├── frontend/                        # Interfaz gráfica (Tkinter)
│   ├── __init__.py
│   ├── main.py                      # Ventana principal y punto de entrada de la UI
│   ├── motor.py                     # Fachada integradora del motor para la interfaz gráfica
│   ├── panel_archivos.py            # Panel 1: tablas cargadas, esquema y estadísticas de páginas
│   ├── panel_consultas.py           # Panel 2: editor y ejecutor de consultas SQL multilínea
│   ├── panel_resultados.py          # Panel 3: visor tabular de resultados de consultas
│   └── panel_plan_ejecucion.py      # Panel 4: visor de árboles y nodos del plan de ejecución
│
├── benchmarks/                      # Comparación experimental de técnicas (Parte 1)
│   ├── __init__.py
│   ├── README.md                    # Documentación y guía de benchmarks
│   ├── _common.py                   # Utilidades de medición de tiempo, memoria y espacio en disco
│   ├── generate_datasets.py         # Generador de datasets sintéticos (1K, 10K, 100K registros)
│   ├── bench_storage.py             # Benchmark: Heap File vs Archivo Secuencial Paginado
│   ├── bench_indexes.py             # Benchmark: B+ Clustered vs B+ Unclustered vs Extendible Hashing
│   ├── concurrency_demo.py          # Demostración interactiva de transacciones concurrentes
│   └── results/                     # Gráficas generadas (.png) y tablas de métricas (.csv)
│
├── tests/                           # Suite completa de pruebas unitarias
│   ├── __init__.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── test_heap_file.py
│   │   └── test_sequential_file.py
│   ├── indexes/
│   │   ├── __init__.py
│   │   ├── test_bplus_tree.py
│   │   ├── test_bplus_clustered.py
│   │   ├── test_bplus_unclustered.py
│   │   ├── test_extendible_hash.py
│   │   ├── test_extendible_hash_bulk.py
│   │   └── test_extendible_hash_persistence.py
│   ├── query/
│   │   ├── __init__.py
│   │   ├── test_lexer.py
│   │   ├── test_parser.py
│   │   ├── test_sql_optimizer.py
│   │   ├── test_planner_executor.py
│   │   ├── test_sql_execution.py
│   │   ├── test_external_algorithms.py
│   │   └── test_temp_records.py
│   └── concurrency/
│       ├── __init__.py
│       └── test_transactions.py
│
└── docs/                            # Documentación técnica y especificaciones
    ├── informe.md                   # Informe incremental del proyecto (diseño, algoritmos, pruebas)
    ├── README.md                    # Índice de documentación técnica
    ├── bplus_indexes.md             # Especificación técnica de los índices B+ Tree
    ├── sql_parser.md                # Especificación técnica del parser SQL y AST
    └── sql_grammar.ebnf             # Gramática formal EBNF de las sentencias SQL soportadas
```

---

## Descripción de cada componente

- **`engine/storage/`**: Capa de persistencia física en disco.
  - **Heap File (`heap_file.py`)**: Almacenamiento en páginas fijas de 4 KB con arquitectura *Slotted Page*, eliminación lógica y reutilización dinámica de espacio.
  - **Sequential File (`sequential_file.py`)**: Almacenamiento ordenado por clave con archivo principal (`main`), área de desborde (`aux`), búsqueda binaria multinivel y reorganización automática con factor de llenado (`fill_factor`).
  - **Record (`record.py`)**: Definición de esquemas de datos (`Schema`) y serialización/deserialización binaria compacta.

- **`engine/indexes/`**: Estructuras de acceso secundario y primario.
  - **B+ Tree (`bplus_tree.py`, `bplus_tree_clustered.py`, `bplus_tree_unclustered.py`)**: Implementación en disco de índices en árbol B+ tanto agrupados (registros en nodos hoja) como no agrupados (punteros directos `RID`), con soporte de búsquedas por igualdad y por rango.
  - **Extendible Hashing (`extendible_hash.py`)**: Índice hash dinámico en disco con directorio de profundidad global y páginas de buckets con profundidad local.

- **`engine/query/`**: Procesamiento, optimización y ejecución de consultas SQL.
  - **Pipeline SQL**: `lexer.py` (tokenizado) $\to$ `parser.py` (análisis sintáctico) $\to$ `ast.py` (árbol de sintaxis) $\to$ `logical_plan.py` / `planner.py` (plan lógico) $\to$ `sql_optimizer.py` (selección de índices) $\to$ `sql_executor.py` / `statement_executor.py` (ejecución contra storage e índices).
  - **Algoritmos Externos (`external_algorithms.py`)**: External Merge Sort de 2 fases (para cláusulas `ORDER BY`) y External Hash Partitioning (para agrupaciones `GROUP BY` y joins) operando bajo memoria RAM acotada.

- **`engine/concurrency/`**: Control de transacciones ACID.
  - **`lock_manager.py`**: Bloqueo estricto en dos fases (Strict 2PL) a nivel de tabla con soporte para modos compartido (`SHARED`) y exclusivo (`EXCLUSIVE`).
  - **`transaction.py` & `transaction_manager.py`**: Gestión de identificadores de transacción, estados (`ACTIVE`, `COMMITTED`, `ABORTED`) y liberación automática de recursos.

- **`frontend/`**: Aplicación de escritorio construida en Python (Tkinter).
  - Integrada a través de `motor.py`, proporcionando los 4 paneles requeridos: catálogo de archivos y páginas, consola de consultas SQL, visualizador de resultados y árbol explicativo del plan de ejecución.

- **`benchmarks/`**: Batería de pruebas de rendimiento experimental para evaluar tiempos de inserción, búsquedas exactas, escaneos por rango, consumo de memoria y tamaño en disco entre las diferentes estructuras de almacenamiento e índices.

- **`tests/`**: Suite de pruebas unitarias exhaustiva con cobertura para cada submódulo del motor.

- **`docs/`**: Especificaciones formales (EBNF), manuales de implementación de índices y parser, e informe académico incremental (`informe.md`).

---

## Ejecución del Proyecto

### 1. Interfaz Gráfica (Frontend)

Para iniciar la aplicación visual de 4 paneles:

```bash
python -m frontend.main
```

### 2. Pruebas Unitarias

Para ejecutar la suite completa de tests:

```bash
python -m unittest discover tests -v
```

Para ejecutar una categoría específica:

```bash
# Pruebas de almacenamiento (Heap File y Sequential File)
python -m unittest discover tests/storage -v

# Pruebas de índices (B+ Tree y Extendible Hashing)
python -m unittest discover tests/indexes -v

# Pruebas del motor de consultas (Lexer, Parser, Optimizador, Algoritmos Externos)
python -m unittest discover tests/query -v

# Pruebas de transacciones y concurrencia
python -m unittest discover tests/concurrency -v
```

### 3. Benchmarks Experimentales

Para generar datasets sintéticos y ejecutar los experimentos:

```bash
# Generar datasets (1K, 10K, 100K)
python -m benchmarks.generate_datasets

# Benchmark de Almacenamiento (Heap File vs Sequential File)
python -m benchmarks.bench_storage

# Benchmark de Índices (B+ Clustered vs Unclustered vs Extendible Hashing)
python -m benchmarks.bench_indexes

# Demostración de Transacciones y Concurrencia
python -m benchmarks.concurrency_demo
```
