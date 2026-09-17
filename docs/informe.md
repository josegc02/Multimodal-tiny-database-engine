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

#### 2.3 Índice Hash Dinámico (Extendible Hashing)

Implementado en `engine/indexes/extendible_hash.py` para acelerar búsquedas por igualdad sobre registros almacenados en Heap File o Sequential File. El índice mantiene un directorio global y buckets con capacidad configurable, adaptando su estructura mediante divisiones y fusiones.

* **Directorio Global y Buckets**:
  - El directorio contiene `2 ** global_depth` referencias a buckets. Inicialmente, la profundidad global es **1** y existen **dos buckets** con profundidad local **1**.
  - Cada bucket almacena pares **`(clave, RID)`**, conservando el registro completo en el archivo de datos. El RID incluye `page_id`, `slot_id` y `file`, permitiendo distinguir `main` y `aux`.
  - `bucket_capacity` limita la cantidad de pares por bucket (**4 por defecto**). Varias entradas del directorio pueden apuntar al mismo bucket cuando su profundidad local es menor que la global.

* **Función Hash y Profundidades**:
  - Se utiliza **BLAKE2b de 64 bits** sobre una representación estable de la clave, evitando la variación de `hash(str)` entre procesos de Python.
  - Los bits menos significativos seleccionan la posición del directorio mediante `hash_clave & ((1 << global_depth) - 1)`. La profundidad global determina cuántos bits se consultan y la local cuántos identifican a cada bucket.
  - Se admiten claves `int`, `float` finitos y `str`. Valores numéricamente iguales, como `1` y `1.0`, se consideran la misma clave.

* **Inserción, Split y Duplicación del Directorio**:
  - `insert(key, rid)` localiza el bucket y agrega el par si existe espacio. Las claves repetidas con distintos RIDs están permitidas; un par idéntico no se inserta dos veces.
  - Si el bucket está lleno y sus entradas pueden separarse, se incrementa su profundidad local, se crea un bucket hermano y se redistribuyen los pares según el nuevo bit disponible.
  - Cuando la profundidad local iguala la global antes del split, se duplica el directorio y se incrementa la profundidad global, conservando las referencias a los buckets que no se dividen.

* **Colisiones y Buckets de Desborde (Decisión de Diseño)**:
  - Las claves repetidas y los hashes que no se pueden separar con los bits disponibles utilizan una cadena de buckets de desborde, cada uno sujeto a `bucket_capacity`.
  - `max_depth` limita el crecimiento del directorio (**16 por defecto**, configurable entre **1 y 20**). Al alcanzar ese límite también se utiliza desborde, evitando divisiones indefinidas.

* **Búsqueda por Igualdad**:
  - `search(key)` accede al bucket indicado por el hash y recorre sus entradas y su cadena de desborde, comparando las claves para distinguir colisiones.
  - Devuelve todos los RIDs coincidentes, o una lista vacía si la clave no existe. Los registros completos se recuperan mediante `storage.get(rid)`; el índice no implementa búsquedas por rango.

* **Eliminación, Merge y Contracción**:
  - `delete(key, rid)` elimina un par específico; sin RID, elimina todas las entradas de la clave. La operación devuelve la cantidad de pares eliminados y compacta la cadena de desborde.
  - Se fusionan buckets hermanos cuando tienen la misma profundidad local y sus entradas combinadas caben en un solo bucket. Las referencias del directorio se actualizan al bucket resultante.
  - Si ambas mitades del directorio contienen las mismas referencias, este se reduce a la mitad. La contracción se repite hasta donde sea posible, manteniendo una profundidad global mínima de **1**.

* **Carga Masiva e Integración con Storage**:
  - `bulk_load` recibe un iterable de pares `(clave, RID)`. `bulk_load_from_storage` obtiene esos pares recorriendo los registros activos del archivo mediante `scan()` y extrayendo el campo indexado.
  - Se agregó `SequentialFile.scan()` para recorrer `main` y `aux` con sus RIDs físicos actuales, omitiendo registros eliminados. La fuente se procesa de forma incremental, mientras el índice resultante reside en memoria.
  - La carga desde storage reconstruye el índice por defecto: solo reemplaza la estructura anterior cuando termina correctamente. Si falla, conserva el índice anterior; durante la construcción ambas estructuras ocupan memoria.
  - Las inserciones ordenadas y reorganizaciones del Sequential File pueden invalidar RIDs existentes, por lo que requieren reconstruir el índice antes de consultarlo. La sincronización entre storage e índice es responsabilidad de la aplicación.

* **Persistencia Opcional y Alcance**:
  - El directorio y los buckets operan en memoria. Al especificar `filepath`, se guarda un **snapshot JSON versionado** con la configuración y los pares mediante `flush()`, `close()` o al salir de un bloque `with`.
  - El guardado escribe un archivo temporal y reemplaza el destino al terminar. Al reabrir, se reconstruye el directorio a partir de las entradas persistidas.
  - Esta implementación no utiliza páginas de buckets en disco ni proporciona transacciones entre el índice y el storage. `stats()` reporta profundidad, entradas, buckets únicos, desborde y ocupación sin contar dos veces las referencias compartidas.

* **Validación mediante Pruebas**:
  - Las pruebas cubren splits con y sin duplicación del directorio, claves repetidas, colisiones forzadas, eliminación y fusión de buckets, y operaciones aleatorias contrastadas con un modelo de referencia.
  - También verifican carga masiva desde ambos storages, reconstrucción tras cambios de RIDs y persistencia entre procesos, incluyendo la conservación del snapshot anterior ante un fallo de guardado.

### 3. Resultados Experimentales y Benchmarks
*(Tablas y gráficas comparativas generadas)*
