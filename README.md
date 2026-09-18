# Motor de Base de Datos Relacional — Avance 1

Proyecto de Base de Datos II para la implementación de un motor de base de datos relacional y multimodal desde cero.

---

## Estructura del proyecto — Avance 1 (Parte 1: Base de Datos Relacional)

```text
Multimodal-tiny-database-engine/
├── README.md                       # este archivo: arquitectura, instalación, uso
├── LICENSE                         # licencia del proyecto
├── requirements.txt                 # dependencias Python del proyecto
├── .gitignore                       # __pycache__/, *.db, *.bpt, venv/, demo_data/, results/
├── setup_avance1.ps1                # script de setup para Windows
├── setup_avance1.sh                 # script de setup para Linux/Mac
│
├── engine/                          # motor de base de datos (código fuente principal)
│   ├── __init__.py
│   │
│   ├── storage/                     # Gestión de archivos y almacenamiento en disco
│   │   ├── __init__.py
│   │   ├── heap_file.py             # Heap File: páginas slotted, reutilización de espacio
│   │   ├── sequential_file.py       # Archivo Secuencial Paginado: orden por clave, reorganización
│   │   └── record.py                # Schema y (de)serialización de registros, compartido por ambos
│   │
│   ├── indexes/                     # Estructuras de indexación
│   │   ├── __init__.py
│   │   ├── bplus_tree.py            # Base del índice B+ paginado (nodos internos y hojas)
│   │   ├── bplus_tree_clustered.py  # B+ agrupado: registros completos en hojas
│   │   ├── bplus_tree_unclustered.py# B+ no agrupado: hojas con (clave, RID)
│   │   └── extendible_hash.py       # Índice Hash Dinámico (Extendible Hashing)
│   │
│   ├── query/                       # Procesamiento de consultas SQL
│   │   ├── __init__.py
│   │   ├── _temp_records.py         # Persistencia temporal para algoritmos externos
│   │   ├── ast.py                   # AST inmutable del dialecto SQL
│   │   ├── catalog.py               # Catálogo de storages e índices registrados
│   │   ├── errors.py                # Errores SQL (sintaxis, semántica, ejecución)
│   │   ├── executor.py              # Ejecución de planes físicos sobre storage/índices
│   │   ├── expressions.py           # Evaluación de expresiones SQL (3-valued logic)
│   │   ├── external_algorithms.py   # External Sort (ORDER BY), External Hash (GROUP BY/JOIN)
│   │   ├── lexer.py                 # Tokenizador de SQL
│   │   ├── logical_plan.py          # Construcción y validación del plan lógico
│   │   ├── parser.py                # Parser: SELECT/INSERT/DELETE/WHERE/ORDER BY/GROUP BY
│   │   ├── planner.py               # Decide qué índice o algoritmo usar por consulta
│   │   ├── sql_executor.py          # Ejecuta planes lógicos contra storages e índices
│   │   ├── sql_optimizer.py         # Optimizador: elige índices y algoritmos físicos
│   │   └── statement_executor.py    # Despacho de sentencias AST con transacciones
│   │
│   └── concurrency/                 # Transacciones y control de concurrencia
│       ├── __init__.py
│       ├── lock_manager.py          # Locks compartidos/exclusivos + detección de deadlocks
│       ├── transaction.py           # Clase Transaction: estado, locks, undo_log
│       └── transaction_manager.py   # BEGIN/COMMIT/ROLLBACK, coordinación con storage
│
├── frontend/                        # Interfaz gráfica con los 4 paneles requeridos
│   ├── __init__.py
│   ├── main.py                      # punto de entrada de la UI
│   ├── motor.py                     # fachada del motor: catalog + managers + executors
│   ├── panel_archivos.py            # tablas cargadas y su estructura
│   ├── panel_consultas.py           # editor de consultas SQL
│   ├── panel_resultados.py          # tabla de resultados de la consulta
│   └── panel_plan_ejecucion.py      # visualización del plan (índices usados, orden de ops)
│
├── benchmarks/                      # Comparación experimental de técnicas (Parte 1)
│   ├── __init__.py
│   ├── generate_datasets.py         # genera datasets sintéticos (1K/5K/10K registros)
│   ├── bench_storage.py             # Heap File vs Archivo Secuencial Paginado
│   ├── bench_indexes.py             # B+ agrupado vs B+ no agrupado vs Hash Dinámico
│   ├── concurrency_demo.py          # simulación con hilos: race conditions, locks, deadlocks
│   ├── plot_results.py              # genera gráficas comparativas a partir de los benchmarks
│   └── results/                     # gráficas (.png) y datasets (.csv) generados
│       └── .gitkeep                 # marcador para que Git mantenga la carpeta
│
├── tests/                           # Tests unitarios (espeja la estructura de engine/)
│   ├── __init__.py
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── test_heap_file.py
│   │   └── test_sequential_file.py
│   │
│   ├── indexes/
│   │   ├── __init__.py
│   │   ├── test_bplus_tree.py
│   │   ├── test_bplus_clustered.py
│   │   ├── test_bplus_unclustered.py
│   │   ├── test_extendible_hash.py
│   │   ├── test_extendible_hash_bulk.py
│   │   └── test_extendible_hash_persistence.py
│   │
│   ├── query/
│   │   ├── __init__.py
│   │   ├── test_external_algorithms.py
│   │   ├── test_lexer.py
│   │   ├── test_parser.py
│   │   ├── test_planner_executor.py
│   │   ├── test_sql_execution.py
│   │   ├── test_sql_optimizer.py
│   │   └── test_temp_records.py
│   │
│   └── concurrency/
│       ├── __init__.py
│       └── test_transactions.py
│
└── docs/                            # documentación del proyecto
    ├── README.md                    # índice de la documentación
    ├── informe.md                   # informe incremental: diseño, algoritmos, resultados
    ├── bplus_indexes.md             # documentación de los índices B+
    ├── sql_grammar.ebnf             # gramática formal del dialecto SQL
    └── sql_parser.md                # documentación del parser
```

---

## Descripción de cada carpeta

- **`engine/`**: Núcleo del motor de base de datos. Todo lo que implementa lógica de bajo nivel (almacenamiento, índices, parser, concurrencia) vive aquí, desacoplado de la interfaz gráfica.
- **`engine/storage/`**: Formas de persistir registros en disco: Heap File y Archivo Secuencial Paginado, más la serialización de registros compartida entre ambos.
- **`engine/indexes/`**: Estructuras que aceleran las búsquedas: B+ Tree (agrupado y no agrupado) y Hash Dinámico.
- **`engine/query/`**: Parser SQL y motor de ejecución: convierte una consulta en texto en un plan ejecutable contra `storage/` e `indexes/`.
- **`engine/concurrency/`**: Transacciones y locking para permitir accesos simultáneos de forma segura.
- **`frontend/`**: Interfaz gráfica con los 4 paneles pedidos (archivos, consultas, resultados, plan de ejecución).
- **`benchmarks/`**: Scripts que generan datasets y miden tiempos/espacio de cada técnica implementada, con sus resultados (gráficas y tablas) para el informe.
- **`tests/`**: Pruebas unitarias, organizadas con la misma jerarquía que `engine/` para que sea fácil ubicar el test de cada módulo.
- **`docs/`**: Informe incremental del curso (diseño arquitectónico, algoritmos, resultados experimentales).

---

## Ejecución de Tests

Para ejecutar todos los tests unitarios del proyecto:

```bash
python -m unittest discover tests -v
```

O ejecutar un módulo de tests específico:

```bash
python -m unittest tests/storage/test_heap_file.py -v
```
