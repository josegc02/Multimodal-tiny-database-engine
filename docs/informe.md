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

#### 2.2 Archivo Secuencial Paginado (Sequential File)
Diseñado para tablas con orden físico por clave primaria o de ordenamiento, combinando páginas ordenadas con un área de desborde y reorganización periódica.

* **Estructura Física Dual (`main` y `aux`)**:
  - **`main`**: Páginas donde los registros y el directorio de slots se mantienen estrictamente ordenados por clave.
  - **`aux`**: Archivo de desborde (*overflow*) sin orden para inserciones rápidas cuando la página destino de `main` no cuenta con espacio suficiente.
  - **Identificador `RID(page_id, slot_id, file)`**: Registra el archivo de origen (`"main"` o `"aux"`), permitiendo accesos y eliminaciones transparentes.

* **Búsqueda e Inserción Binaria en Dos Niveles**:
  - **Nivel de Archivo**: Búsqueda binaria sobre una tabla en memoria de rangos de claves `_page_bounds` `[(min_key, max_key)]` por página.
  - **Nivel de Página**: Búsqueda binaria directa sobre el directorio de slots (`_binary_search_in_page` para búsquedas e `_find_insert_position_in_page` para inserción).
  - **Inserción ordenada eficiente**: `insert_sorted_at` desplaza únicamente las entradas del directorio de slots (5 bytes por slot) hacia la izquierda en memoria, sin reubicar los datos de los registros. Si la página está llena, el registro se almacena en `aux`.

* **Eliminación Lógica**:
  - Marca `is_deleted = 1` en el slot sin compactación inmediata física y actualiza `_page_bounds` para mantener la coherencia de los límites del archivo.

* **Inestabilidad de RIDs en `main` (Trade-off de Diseño)**:
  - A diferencia del Heap File, los RIDs devueltos por operaciones de inserción en `main` no son estables frente a inserciones posteriores en la misma página, dado que el reordenamiento del directorio de slots desplaza el `slot_id` de los registros existentes. Por diseño, el acceso recomendado a este storage es mediante `search_by_key`, no mediante almacenamiento externo persistente de RIDs.

* **Disparador de Reorganización (>30%)**:
  - `needs_reorganization()` monitorea el porcentaje de registros obsoletos o desbordados: `(deleted_main + aux_count) / total > 0.30`. Al superarse este umbral, se requiere compactación.

* **Reorganización con `fill_factor` (Decisión Propia de Diseño)**:
  - Se extraen todos los registros activos de `main` y `aux`, se ordenan por clave y se purgan definitivamente los registros eliminados.
  - Se reconstruye `main` aplicando un `fill_factor` (**0.9 / 90%** de capacidad por página). Esta holgura del 10% es una optimización de diseño para admitir futuras inserciones ordenadas directamente en `main` sin provocar desbordes inmediatos hacia `aux`, evitando reorganizaciones consecutivas prematuras.

### 3. Resultados Experimentales y Benchmarks
*(Tablas y gráficas comparativas generadas)*
