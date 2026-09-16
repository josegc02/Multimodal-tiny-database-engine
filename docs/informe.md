# Informe del Proyecto — Base de Datos II

## Avance 1: Motor Relacional

### 1. Arquitectura del Motor
- **Almacenamiento**: Heap File (Slotted Page) y Archivo Secuencial Paginado.
- **Índices**: B+ Tree Clustered, B+ Tree Unclustered, Extendible Hashing.
- **Consultas**: Lexer, Parser SQL, Planner, Executor y Algoritmos Externos.
- **Concurrencia**: Lock Manager (Shared/Exclusive) y control de transacciones.
- **Frontend**: Interfaz gráfica de 4 paneles (archivos, consultas, resultados, plan).

### 2. Decisiones de Diseño y Algoritmos

#### 2.1 Heap File con Arquitectura Slotted Page
Se implementó el almacenamiento en disco mediante páginas de tamaño fijo (**4096 bytes / 4 KB**), alineadas con el tamaño de bloque del sistema operativo y hardware de almacenamiento.

* **Estructura de Página**:
  - **Header (4 bytes)**: `num_slots` (uint16) y `data_end` (uint16).
  - **Área de Datos**: Crece desde el inicio (byte 4) hacia adelante.
  - **Directorio de Slots**: Crece desde el final (byte 4096) hacia atrás. Cada slot ocupa **5 bytes** (`offset: 2B`, `length: 2B`, `is_deleted: 1B`).
  - **Espacio Libre**: Bloque continuo en el centro (`slot_dir_start - data_end`), evitando fragmentación y eliminando la necesidad de desplazar datos en memoria.

* **Estabilidad de Punteros (RID)**:
  - Cada registro es identificado de forma única por un `RID(page_id, slot_id)`.
  - Se utiliza **eliminación lógica** (`is_deleted = 1` en el slot), preservando la posición física del slot para que los índices externos (B+ Tree y Hash) no queden corruptos.

* **Reutilización de Espacio**:
  - En inserciones, el motor primero busca slots marcados como eliminados para sobreescribir su espacio antes de consumir nuevo espacio contiguo.
  - El motor mantiene en memoria un conjunto `free_pages` que se actualiza dinámicamente con las páginas candidatas para inserción sin requerir escaneos completos de disco.

### 3. Resultados Experimentales y Benchmarks
*(Tablas y gráficas comparativas generadas)*
