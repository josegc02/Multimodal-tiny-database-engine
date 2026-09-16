# Motor de Base de Datos Relacional — Avance 1

Proyecto de Base de Datos II para la implementación de un motor de base de datos relacional y multimodal desde cero.

---

## Estructura del proyecto — Avance 1 (Parte 1: Base de Datos Relacional)

```text
minigestor-bd/
├── README.md                       # este archivo: arquitectura, instalación, uso
├── requirements.txt                 # dependencias Python del proyecto
├── .gitignore                       # __pycache__/, *.heap, *.db, venv/, results/
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
│   │   ├── bplus_tree.py            # Índice B+ agrupado (clustered)
│   │   ├── bplus_tree_unclustered.py# Índice B+ no agrupado (apunta a RID)
│   │   └── extendible_hash.py       # Índice Hash Dinámico (Extendible Hashing)
│   │
│   ├── query/                       # Procesamiento de consultas SQL
│   │   ├── __init__.py
│   │   ├── lexer.py                 # Tokenizador de SQL
│   │   ├── parser.py                # Parser: SELECT/INSERT/DELETE/WHERE/ORDER BY/GROUP BY
│   │   ├── planner.py               # Decide qué índice o algoritmo usar por consulta
│   │   ├── executor.py              # Ejecuta el plan contra storage/índices
│   │   └── external_algorithms.py   # External Sort (ORDER BY), External Hash (GROUP BY/JOIN)
│   │
│   └── concurrency/                 # Transacciones y control de concurrencia
│       ├── __init__.py
│       ├── lock_manager.py          # Locks compartidos/exclusivos
│       └── transaction.py           # BEGIN/END TRANSACTION, manejo de sesiones concurrentes
│
├── frontend/                        # Interfaz gráfica con los 4 paneles requeridos
│   ├── __init__.py
│   ├── main.py                      # punto de entrada de la UI
│   ├── panel_archivos.py            # tablas cargadas y su estructura
│   ├── panel_consultas.py           # editor de consultas SQL
│   ├── panel_resultados.py          # tabla de resultados de la consulta
│   └── panel_plan_ejecucion.py      # visualización del plan (índices usados, orden de ops)
│
├── benchmarks/                      # Comparación experimental de técnicas (Parte 1)
│   ├── __init__.py
│   ├── generate_datasets.py         # genera datasets sintéticos (1K/10K/100K registros)
│   ├── bench_storage.py             # Heap File vs Archivo Secuencial Paginado
│   ├── bench_indexes.py             # B+ agrupado vs B+ no agrupado vs Hash Dinámico
│   └── results/                     # gráficas (.png) y tablas (.csv) generadas
│
├── tests/                           # Tests unitarios (espeja la estructura de engine/)
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── test_heap_file.py
│   │   └── test_sequential_file.py
│   ├── indexes/
│   │   ├── __init__.py
│   │   ├── test_bplus_tree.py
│   │   └── test_extendible_hash.py
│   ├── query/
│   │   ├── __init__.py
│   │   └── test_parser.py
│   └── concurrency/
│       ├── __init__.py
│       └── test_transactions.py
│
└── docs/
    └── informe.md                   # informe incremental: diseño, algoritmos, resultados
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
