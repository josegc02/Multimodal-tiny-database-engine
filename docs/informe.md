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
  - El motor mantiene en memoria un conjunto `free_pages` con las páginas que tienen espacio para un slot nuevo o un slot borrado reutilizable. Se reconstruye al abrir el archivo y se actualiza en cada inserción y eliminación, sin escaneos completos de disco por operación.

#### 2.2 Archivo Secuencial Paginado (Sequential File)
Diseñado para tablas con orden físico por clave primaria o de ordenamiento, combinando páginas ordenadas con un área de desborde y reorganización periódica.

* **Estructura Física Dual (`main` y `aux`)**:
  - **`main`**: Páginas donde los registros y el directorio de slots se mantienen estrictamente ordenados por clave.
  - **`aux`**: Archivo de desborde (*overflow*) sin orden para inserciones rápidas cuando la página destino de `main` no cuenta con espacio suficiente.
  - **Identificador `RID(page_id, slot_id, file)`**: Registra el archivo de origen (`"main"` o `"aux"`), permitiendo accesos y eliminaciones transparentes.

* **Búsqueda e Inserción Binaria en Dos Niveles**:
  - **Nivel de Archivo**: Búsqueda binaria sobre separadores en memoria (`_page_max`, el máximo de cada página de `main`). Si una página queda vacía conserva su último máximo como separador, de modo que la búsqueda binaria no se desvía.
  - **Nivel de Página**: Búsqueda binaria (*lower bound*) sobre el directorio de slots con `_find_insert_position_in_page`.
  - **Inserción ordenada eficiente**: `insert_sorted_at` desplaza únicamente las entradas del directorio de slots (5 bytes por slot), sin reubicar los datos de los registros. Si la página destino está llena, el registro se agrega **al final** de `aux` (sin recorrer `aux` buscando huecos).
  - **Búsqueda por clave y por rango**: `search_by_key` devuelve todas las coincidencias (admite claves repetidas) recorriendo `main` desde el *lower bound* y revisando `aux`; `range_search(lower, upper)` mezcla (*merge*) el tramo ordenado de `main` con las coincidencias de `aux`.

* **Eliminación Lógica**:
  - Marca `is_deleted = 1` en el slot sin compactación inmediata y actualiza los límites de la página. La eliminación nunca dispara una reorganización, así los RIDs de un lote de borrado siguen siendo válidos.

* **Inestabilidad de RIDs en `main` (Trade-off de Diseño)**:
  - A diferencia del Heap File, los RIDs devueltos por inserciones en `main` no son estables: una inserción posterior en la misma página desplaza el `slot_id` de los registros existentes y una reorganización reescribe el archivo. El acceso recomendado es mediante `search_by_key`/`range_search`, y los índices secundarios deben reconstruirse tras modificar la tabla.

* **Disparadores de Reorganización**:
  - `needs_reorganization()` usa contadores en memoria (registros activos y borrados en `main`, registros en `aux`) y devuelve verdadero si:
    1. el **espacio desperdiciado supera el 30%**: `(borrados_main + registros_aux) / total > 0.30`, o
    2. `aux` supera **⌈log₂(páginas de main + 1)⌉ páginas**. Este segundo límite (decisión propia) mantiene la búsqueda en O(log P) lecturas: sin él, con inserciones aleatorias casi todos los registros terminaban en `aux` y la búsqueda degeneraba en un recorrido lineal.
  - Con `auto_reorganize=True` (valor por defecto) la verificación se hace **antes** de cada inserción, de modo que el RID devuelto sigue siendo válido al retornar.

* **Reorganización con `fill_factor` (Decisión Propia de Diseño)**:
  - `main` ya está ordenado, así que se recorre en *streaming*; solo `aux` (acotado por el disparador) se ordena en memoria. Ambos flujos se combinan con un *merge* y se escriben en un archivo nuevo que reemplaza a `main` al terminar (`os.replace`); los registros eliminados se purgan y `aux` queda vacío.
  - Las páginas nuevas se llenan al **90% (`fill_factor = 0.9`)**. La holgura del 10% admite inserciones ordenadas directamente en `main` sin desbordar de inmediato hacia `aux`.

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

### 3.1 Metodología
Las pruebas se ejecutan con scripts de consola independientes del frontend (`benchmarks/bench_storage.py` y `benchmarks/bench_indexes.py`); el detalle completo está en `benchmarks/README.md`.

* **Tamaños de dataset**: **1.000**, **10.000** y **100.000** registros.
* **Datos**: semilla fija **42**; claves únicas 0..N-1 insertadas en orden **aleatorio** (no favorece al Archivo Secuencial). Esquema `id` (int), `nombre` (20 caracteres ASCII) y `precio` (float): **36 bytes por registro**.
* **Páginas** de **4096 bytes** en todas las estructuras.
* **Repeticiones**: **3 corridas por tamaño**. Las tablas reportan la **media**, y las gráficas muestran barras de error de ± 1 desviación estándar (`*_comparison.csv`; cada corrida está en `*_runs.csv`).
* **Gráficas en escala log-log** (también las de espacio), para comparar crecimientos sin distorsiones.
* **Entorno**: Windows 11 (AMD64), Python 3.13.5, sin vaciar la caché del sistema operativo. La corrida de almacenamiento tomó **250 s** y la de índices **1.243 s**.

> **Corrección respecto de la versión anterior de este informe.** La medición original (18/09) tenía tres problemas que invalidaban varias conclusiones:
> 1. El Archivo Secuencial dejaba **una sola página en `main`** y enviaba el resto de los registros a `aux` (con N=10.000: 1 página en `main` y 101 en `aux`). En la práctica se comparaba un heap contra otro heap, la búsqueda del secuencial era lineal y el espacio en disco salía idéntico.
> 2. La búsqueda del Heap recorría el archivo completo aunque la clave fuera primaria, y el B+ no agrupado devolvía RIDs sin leer los registros del heap.
> 3. El B+ recalculaba todos los separadores del camino tras **cada** inserción. Además, todos los índices usaban M = 64, sin importar el tamaño real de sus entradas.
>
> Se corrigieron el motor (secuencial con reorganización automática y separadores del B+ actualizados en O(altura)) y los benchmarks. Todos los números de esta sección provienen de la nueva corrida.

### 3.2 Comparación de Almacenamiento: Heap File vs Archivo Secuencial

#### Tiempo de inserción
![](../benchmarks/results/storage_tiempo_insercion.png)

| N | Heap File | Sequential File | Secuencial / Heap | Reorganizaciones automáticas |
| ---: | ---: | ---: | ---: | ---: |
| 1.000 | 0,094 s | 0,243 s | 2,6× | 4 |
| 10.000 | 0,752 s | 2,176 s | 2,9× | 13 |
| 100.000 | 7,585 s | 24,726 s | 3,3× | 31 |

El Heap File inserta en la primera página con espacio (conjunto `free_pages` en memoria), con costo O(1). El Sequential File hace, en cada inserción, una búsqueda binaria de la página y del slot, y desplaza el directorio de slots. Cuando `aux` supera su límite o el desperdicio pasa del 30%, se reorganiza. El tiempo del secuencial **incluye sus 31 reorganizaciones** en 100.000 registros. Aun así, crece de forma casi lineal: con la versión anterior la misma carga tardaba **1.459 s** (59 veces más), porque cada inserción recorría todo `aux` buscando espacio.

#### Tiempo de búsqueda por clave primaria
![](../benchmarks/results/storage_tiempo_busqueda.png)

Promedio por consulta (100 claves existentes):

| N | Heap File | Secuencial tras la carga | Secuencial tras reorganizar |
| ---: | ---: | ---: | ---: |
| 1.000 | 3,53 ms | 0,84 ms | 0,046 ms |
| 10.000 | 25,43 ms | 0,078 ms | 0,061 ms |
| 100.000 | 255,16 ms | 0,214 ms | 0,068 ms |

* El Heap no tiene orden, así que realiza un recorrido lineal O(N), aun deteniéndose en la primera coincidencia: su tiempo crece 10× cuando N crece 10×.
* El secuencial combina búsqueda binaria en `main` con la revisión de `aux`, que está acotado a ⌈log₂(P+1)⌉ páginas. En 100.000 registros es **1.194 veces más rápido** que el Heap tras la carga y **3.755 veces más rápido** tras reorganizar (con `aux` vacío). Tras reorganizar, el tiempo es prácticamente constante (0,05–0,07 ms), como se espera de O(log N).
* El valor tras la carga depende de cuán lleno quedó `aux` al terminar: en 1.000 registros `aux` puede tener hasta 4 páginas frente a unas 11 de `main`, y su recorrido domina el costo.

#### Espacio en disco
![](../benchmarks/results/storage_espacio_disco.png)

| N | Heap File | Secuencial tras la carga | Secuencial tras borrar 35% y reorganizar |
| ---: | ---: | ---: | ---: |
| 1.000 | 45.056 B | 45.056 B | 32.768 B |
| 10.000 | 417.792 B | 446.464 B (+6,9%) | 303.104 B |
| 100.000 | 4.141.056 B | 4.395.008 B (+6,1%) | 2.994.176 B |

El Heap llena cada página al 100%. El secuencial reconstruye `main` con `fill_factor = 0,9`: deja un 10% libre por página para absorber inserciones y además mantiene algunas páginas en `aux`. Eso explica un sobrecosto de alrededor del 6%. En 1.000 registros, las inserciones posteriores a la última reorganización volvieron a llenar las páginas, y el tamaño coincide con el del Heap.

#### Proceso de reorganización
![](../benchmarks/results/storage_tiempo_reorganizacion.png)

Tras borrar el **35%** de los registros (no cronometrado), `needs_reorganization()` se activa porque el desperdicio supera el **30%**. `reorganize()` tardó **0,026 s**, **0,085 s** y **0,681 s** para 1.000, 10.000 y 100.000 registros: crece de forma lineal con el número de páginas. Como `main` ya está ordenado, se recorre una sola vez y se combina (*merge*) con `aux` ordenado; no hace falta ordenar toda la tabla en memoria. El archivo resultante ocupa un 32% menos que tras la carga. El Heap no necesita reorganizarse, porque reutiliza los slots borrados.

#### Resumen y conclusiones de almacenamiento

| Técnica | Ventajas | Desventajas | Escenario recomendado |
| :--- | :--- | :--- | :--- |
| **Heap File** | Inserción O(1), la más rápida (3,3× frente al secuencial en 100K); RIDs estables; reutiliza slots borrados sin mantenimiento. | Búsqueda por clave O(N): 255 ms por consulta en 100K sin índice; no conserva orden. | Cargas con alta tasa de escritura, o tablas que siempre se consultan mediante un índice secundario. |
| **Sequential File** | Búsqueda por clave y por rango en O(log N): 0,07–0,21 ms en 100K, más de 1.000× más rápida que el heap; datos físicamente ordenados. | Inserción ~3× más lenta (búsqueda binaria + reorganizaciones); RIDs inestables; ~6% más de espacio por el `fill_factor`. | Tablas de lectura predominante con consultas por clave primaria o por rango. |

### 3.3 Comparación de Índices: B+ Agrupado vs B+ No Agrupado vs Hash Dinámico

**Configuración.** Cada estructura usa nodos que llenan una página de 4096 B:
* B+ agrupado: **M = 92**, porque cada entrada de hoja guarda clave + registro de 36 B.
* B+ no agrupado: **M = 254**, porque cada entrada guarda clave + RID de 8 B.
* Hash: buckets de **254 entradas**.

**Todas las consultas devuelven registros completos.** El agrupado los tiene en sus hojas; el no agrupado y el hash leen cada RID de un `HeapFile` real. Así se compara el costo real de responder una consulta.

#### Tiempo de construcción
![](../benchmarks/results/indexes_tiempo_construccion.png)

| N | B+ agrupado | B+ no agrupado | Extendible Hash |
| ---: | ---: | ---: | ---: |
| 1.000 | 0,63 s | 1,17 s | 0,05 s |
| 10.000 | 8,52 s | 13,46 s | 0,70 s |
| 100.000 | 97,19 s | 161,31 s | 9,58 s |

* El hash es **16,8 veces más rápido** que el B+ no agrupado en 100K. Trabaja en RAM y escribe un único snapshot JSON al final (incluido en el tiempo), mientras que el B+ escribe y hace `flush` de cada página que modifica.
* El no agrupado tarda **1,66 veces** más que el agrupado aunque sus entradas son más pequeñas. Con M = 254, cada escritura de nodo serializa casi el triple de entradas que con M = 92.
* Con la versión anterior del B+ (M = 64 y recálculo completo de separadores en cada inserción), construir 100K registros tomaba **698 s** (agrupado) y **443 s** (no agrupado).

#### Búsqueda por igualdad
![](../benchmarks/results/indexes_tiempo_igualdad.png)

Promedio por consulta, registro completo:

| N | B+ agrupado | B+ no agrupado | Extendible Hash |
| ---: | ---: | ---: | ---: |
| 1.000 | 0,25 ms | 0,71 ms | 0,05 ms |
| 10.000 | 0,38 ms | 0,66 ms | 0,09 ms |
| 100.000 | 0,62 ms | 1,00 ms | 0,14 ms |

El hash es el más rápido: calcula el bucket directamente (BLAKE2b) en RAM y hace **una sola lectura** del heap. El B+ agrupado lee la altura del árbol y encuentra el registro en la hoja. El no agrupado lee la altura del árbol **más** una página del heap. Por eso es entre 1,6 y 2,8 veces más lento que el agrupado. Los tres crecen poco con N (O(1) y O(log N)).

#### Búsqueda por rango
![](../benchmarks/results/indexes_tiempo_rango.png)

Promedio de 20 rangos `[k, k+100]` (101 registros):

| N | B+ agrupado | B+ no agrupado |
| ---: | ---: | ---: |
| 1.000 | 0,80 ms | 2,95 ms |
| 10.000 | 1,11 ms | 2,80 ms |
| 100.000 | 1,55 ms | 5,40 ms |

En el **agrupado** los 101 registros están contiguos en 1 o 2 hojas. El **no agrupado** recorre sus hojas, pero debe leer cada uno de los 101 RIDs en una página distinta del heap. Como los datos se insertaron en orden aleatorio, claves vecinas quedan en páginas distintas, y el agrupado resulta **3,5 veces más rápido** en 100K. (La versión anterior del informe concluía lo contrario porque el no agrupado no leía los registros.) El **Extendible Hash no soporta rangos**: la función hash dispersa claves consecutivas en buckets distintos.

#### Ordenamiento (ORDER BY)
![](../benchmarks/results/indexes_tiempo_orden.png)

`ORDER BY id` sobre toda la tabla: **0,45 s** (agrupado), **3,93 s** (no agrupado) y **15,41 s** (hash) con 100K registros.
* El agrupado recorre sus hojas encadenadas, que ya están ordenadas.
* El no agrupado obtiene el orden de sus hojas, pero hace una lectura aleatoria del heap por cada registro.
* El hash no aporta orden, así que el motor recurre a `scan` del heap + *external sort* k-way. Es 34 veces más lento que el agrupado.

#### Espacio en disco y memoria
![](../benchmarks/results/indexes_espacio_total.png)

Espacio total de **tabla + índice** con 100K registros (el heap solo, sin índice, ocupa 4.141.056 B):
* **B+ agrupado**: 6.496.256 B, en un solo archivo (1.585 nodos). Ocupa 2,36 MB más que el heap porque sus hojas quedan llenas en promedio al ~69% tras los splits.
* **B+ no agrupado**: heap + 2,21 MB de índice (539 nodos), en total 6.352.896 B.
* **Extendible Hash**: heap + snapshot JSON de 2,17 MB, en total 6.310.040 B. En ejecución ocupa además **23,8 MB de RAM** (directorio de 512 entradas, 512 buckets, factor de carga 0,77), porque el índice vive completo en memoria.

Los tres terminan ocupando de 1,52 a 1,57 veces lo que ocupa el heap solo. La diferencia más importante es que el hash consume RAM proporcional a N.

#### Inserciones y eliminaciones frecuentes
![](../benchmarks/results/indexes_tiempo_actualizaciones.png)

500 ciclos de inserción + eliminación (1.000 operaciones, en tabla e índice): **17,4 s** (agrupado), **23,9 s** (no agrupado) y **1,79 s** (hash) en 100K.
* El hash resuelve cada operación en RAM con splits y merges locales.
* En el B+, la eliminación sigue recalculando los separadores del camino con `_first_key`. Es el costo dominante y la siguiente optimización pendiente, igual a la que ya se aplicó a la inserción.

#### Resumen y conclusiones de índices

| Técnica | Ventajas | Desventajas | Escenario recomendado |
| :--- | :--- | :--- | :--- |
| **B+ Agrupado** | El mejor en rangos (3,5× frente al no agrupado) y en ORDER BY (8,7×); igualdad en O(log N) sin I/O adicional. | Solo uno por tabla (define el orden físico); splits mueven registros completos; ~57% más espacio que un heap. | Clave primaria de tablas con consultas de rango, ordenamientos o recorridos por clave. |
| **B+ No Agrupado** | Rangos y orden sobre cualquier columna; permite varios por tabla; claves duplicadas. | Una lectura aleatoria del heap por registro: 3,5× más lento que el agrupado en rangos y 8,7× en ORDER BY. | Índices secundarios sobre columnas con filtros de rango selectivos (pocos registros por consulta). |
| **Extendible Hash** | La igualdad más rápida (0,14 ms en 100K) y las actualizaciones más baratas; construcción 16,8× más rápida. | No soporta rangos ni orden; reside en RAM (23,8 MB para 100K) y persiste por snapshot completo. | Búsquedas exactas y joins por igualdad sobre claves que no se consultan por rango. |

### 3.4 Conclusión general de la Parte 1
No existe una estructura óptima para todo: cada una equilibra de forma distinta el costo de escritura, la latencia de lectura y el consumo de recursos.
* Para **alta tasa de escritura con consultas de punto exacto**, la mejor combinación es **Heap File + Extendible Hash**: inserción O(1) y búsqueda en ~0,1 ms, a cambio de mantener el índice en RAM.
* Para **consultas por rango u ordenamiento sobre la clave primaria**, conviene un **B+ agrupado**, o un **Sequential File** si la tabla se lee mucho más de lo que se escribe. Las mediciones corregidas muestran que la búsqueda binaria del secuencial supera al heap por más de tres órdenes de magnitud, a cambio de insertar ~3 veces más lento.
* El **B+ no agrupado** se justifica para columnas secundarias con filtros selectivos. En rangos grandes o en ORDER BY de toda la tabla, sus lecturas aleatorias al heap lo vuelven varias veces más lento que el agrupado.
