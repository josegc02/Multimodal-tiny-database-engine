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

### 3.1 Metodología
Las pruebas experimentales se desarrollaron mediante scripts de consola independientes del frontend (`benchmarks/bench_storage.py` y `benchmarks/bench_indexes.py`), garantizando aislamiento y reproducibilidad sin interferencias de la interfaz de usuario:

* **Tamaños de dataset evaluados**: Se ejecutaron los tres tamaños oficiales establecidos por el proyecto: **1.000**, **10.000** y **100.000** registros.
* **Generación de claves y aleatoriedad**: El generador `generate_datasets.py` utilizó una semilla fija (**42**) para garantizar reproducibilidad exacta. Las claves se insertaron en orden **estrictamente aleatorio**, decisión metodológica fundamental para no favorecer artificialmente al Archivo Secuencial con inserciones preordenadas.
* **Esquema y tamaño de registros**: Esquema relacional compuesto por `id` (int), `nombre` (cadena ASCII fija de 20 caracteres) y `precio` (float), con un tamaño constante de **36 bytes por registro**.
* **Tamaño de página**: Páginas de disco de **4096 bytes** (4 KB), alineadas al bloque típico del sistema operativo.
* **Entorno y duraciones de ejecución**: Las pruebas se ejecutaron sobre arquitectura Linux x86_64 con Python 3.14.7 y matplotlib 3.11.2, utilizando almacenamiento en `/tmp` sobre sistema de archivos en memoria `tmpfs`. La corrida completa de almacenamiento requirió **1.513,481 s** (~25,2 minutos) y la de índices **1.231,015 s** (~20,5 minutos), totalizando **2.744,496 s** (~45,7 minutos) de experimentación continua.

### 3.2 Comparación de Almacenamiento: Heap File vs Archivo Secuencial

#### Tiempo de inserción
![](../benchmarks/results/storage_tiempo_insercion.png)

La gráfica refleja una divergencia de rendimiento crítica entre ambas organizaciones físicas:
* Para 1.000 registros, Heap File completó la inserción en **0,022871 s** frente a **0,149530 s** de Sequential File (**6,54 veces** más lento el secuencial).
* Con 10.000 registros, Heap File tardó **0,237460 s** frente a **14,286807 s** de Sequential File (**60,17 veces** de diferencia).
* Al alcanzar los 100.000 registros, Heap File insertó en **2,296409 s** mientras que Sequential File demoró **1.459,402136 s** (~24,32 minutos), resultando en una degradación masiva de **635,51 veces**.

Esta marcada diferencia responde a la mecánica interna de cada estructura: Heap File realiza inserciones en $O(1)$ gracias a su lista en memoria `free_pages` y la estrategia slotted page, insertando directamente en la primera página con espacio. Por el contrario, en `SequentialFile` las inserciones aleatorias provocan que las páginas ordenadas de `main` se saturen rápidamente, forzando el desborde hacia `aux`. Al analizar la implementación en `engine/storage/sequential_file.py`, el método `_insert_into_aux` ejecuta una búsqueda lineal página por página (`for page_id in range(self.num_pages_aux)`) tratando de ubicar espacio libre. Con decenas de miles de registros desbordados, cada nueva inserción incurre en un recorrido secuencial acumulativo de cientos de páginas, originando una complejidad empírica de $O(P^2)$ en páginas de disco.

#### Tiempo de búsqueda
![](../benchmarks/results/storage_tiempo_busqueda.png)

La evaluación midió el tiempo total para ejecutar 100 búsquedas puntuales por clave primaria (igualdad):
* Con 1.000 registros, Sequential File tardó **0,069035 s** frente a **0,212630 s** de Heap File (**3,08 veces** más rápido el secuencial).
* Con 10.000 registros, Sequential File requirió **0,804472 s** frente a **2,118676 s** de Heap File (**2,63 veces** más rápido el secuencial).
* Con 100.000 registros, Sequential File resolvió las 100 búsquedas en **8,013247 s** frente a **21,079896 s** de Heap File (**2,63 veces** más rápido el secuencial).

Sequential File demostró una ventaja sistemática de **2,63× a 3,08×** gracias a su esquema de búsqueda binaria en dos niveles: una búsqueda binaria en memoria sobre el índice de límites de páginas `_page_bounds` para ubicar la página candidata, seguida de una búsqueda binaria local sobre el directorio de slots dentro de dicha página. En contraposición, Heap File se ve obligado a escanear linealmente todas las páginas y slots hasta encontrar la coincidencia ($O(N)$). Cabe resaltar que la ventaja del secuencial se vio parcialmente atenuada porque las búsquedas se ejecutaron antes de la reorganización, obligando al secuencial a inspeccionar linealmente las páginas desbordadas de `aux` cuando la clave no se hallaba en `main`.

#### Espacio en disco
![](../benchmarks/results/storage_espacio_disco.png)

El consumo de almacenamiento secundario fue exactamente idéntico para ambas técnicas en todos los órdenes de magnitud:
* Con 1.000 registros: **45.056 bytes** (11 páginas de 4 KB).
* Con 10.000 registros: **417.792 bytes** (102 páginas de 4 KB).
* Con 100.000 registros: **4.141.056 bytes** (~3,95 MB, 1.011 páginas de 4 KB).

Ambas estructuras implementan la misma arquitectura de páginas de 4096 bytes con 4 bytes de cabecera y 5 bytes por slot, almacenando registros serializados uniformes de 36 bytes. En consecuencia, la división física de Sequential File entre los archivos `main` y `aux` distribuye los slots entre dos ficheros pero no introduce holgura adicional neta previa a los borrados.

#### Proceso de reorganización
En el experimento se eliminó aleatoriamente el **35% de los registros** (`deleted_fraction: 0.35`). Esta operación activó el disparador de reorganización de Sequential File definido en `needs_reorganization()`, el cual exige compactación cuando la fracción de registros obsoletos o desbordados supera el umbral del **30%** (`(deleted_main + aux_count) / total > 0.30`). La reorganización física `reorganize()` requirió **0,003647 s** para 1.000 registros, **0,036352 s** para 10.000 registros y **0,374408 s** para 100.000 registros (reconstruyendo los 65.000 registros supervivientes). Durante este proceso se purgan físicamente las entradas eliminadas, se recombina el contenido de `aux` y `main` en secuencia ordenada y se reconstruye `main` aplicando un `fill_factor` de **0,9 (90%)**, dejando un 10% de espacio libre por página para acomodar futuras inserciones sin desborde inmediato.

#### Resumen y conclusiones de almacenamiento

| Técnica | Ventajas | Desventajas | Escenario recomendado |
| :--- | :--- | :--- | :--- |
| **Heap File** | Inserción en $O(1)$ constante y ultrarrápida (2,3 s en 100K); RIDs físicos estables; implementación simple sin necesidad de compactación obligatoria. | Búsqueda por clave primaria lineal lenta sin índice ($O(N)$); nula preservación del orden físico de los datos. | Cargas con alta tasa de escritura (OLTP, ingesta de logs, inserciones masivas frecuentes). |
| **Sequential File** | Búsqueda puntual eficiente mediante búsqueda binaria de dos niveles (2,6× más rápida); almacenamiento físicamente ordenado por clave. | Inserciones aleatorias sumamente costosas por desborde en aux ($O(P^2)$); RIDs inestables tras splits o compactaciones; requiere mantenimiento periódico. | Tablas de lectura predominante con consultas frecuentes por clave primaria o rangos, donde los datos se cargan en lotes masivos previamente ordenados. |

### 3.3 Comparación de Índices: B+ Agrupado vs B+ No Agrupado vs Hash Dinámico

#### Tiempo de construcción
![](../benchmarks/results/indexes_tiempo_construccion.png)

El costo de construir los índices evidenció diferencias fundamentales ligadas a la persistencia y al manejo de datos:
* En 1.000 registros: Extendible Hash tardó **0,007724 s**, frente a **0,475835 s** de B+ no agrupado y **0,880939 s** de B+ agrupado.
* En 10.000 registros: Extendible Hash requirió **0,086604 s**, B+ no agrupado **17,996046 s** y B+ agrupado **34,242905 s**.
* En 100.000 registros: Extendible Hash completó la carga en **1,530415 s**, mientras que B+ no agrupado demoró **442,521788 s** y B+ agrupado **698,397620 s**.

El índice B+ agrupado tardó **1,58 veces** más que el no agrupado (**698,397620 s** frente a **442,521788 s** en 100K) debido a que debe trasladar y reescribir registros completos de 36 bytes en sus nodos hoja durante las divisiones de nodo (*splits*), mientras que el no agrupado solo manipula pares clave-RID de tamaño reducido. Por su parte, Extendible Hash resultó **289,15 veces** más rápido que B+ no agrupado y **456,35 veces** más rápido que B+ agrupado; esto se explica porque el hash opera en memoria RAM sin persistir bloques en disco durante el experimento, mientras que los árboles B+ gestionan páginas físicas de 4096 bytes sincronizadas mediante `flush()`.

#### Búsqueda por igualdad
![](../benchmarks/results/indexes_tiempo_igualdad.png)

Para 100 búsquedas puntuales por coincidencia exacta:
* En 1.000 registros: Extendible Hash tardó **0,000463 s**, B+ no agrupado **0,008788 s** y B+ agrupado **0,010016 s** (Hash fue **18,97 veces** más rápido que B+ no agrupado).
* En 10.000 registros: Extendible Hash tardó **0,000479 s**, B+ no agrupado **0,014537 s** y B+ agrupado **0,015316 s** (Hash fue **30,37 veces** más rápido que B+ no agrupado).
* En 100.000 registros: Extendible Hash resolvió las consultas en **0,000952 s**, B+ no agrupado en **0,018218 s** y B+ agrupado en **0,018516 s** (Hash fue **19,14 veces** más rápido que B+ no agrupado y **19,46 veces** más rápido que B+ agrupado).

Extendible Hash ofrece un rendimiento superior en búsquedas exactas gracias a su acceso $O(1)$: la función hash BLAKE2b determina de forma directa la entrada en el directorio global y el bucket exacto en RAM, eliminando el recorrido descendente por los niveles del árbol B+ que requiere múltiples lecturas de páginas de nodos.

#### Búsqueda por rango
![](../benchmarks/results/indexes_tiempo_rango.png)

Se evaluaron 20 consultas por rango inclusivo `[k, min(N-1, k+100)]` de hasta 101 claves contiguas:
* En 1.000 registros: B+ no agrupado tardó **0,004595 s** y B+ agrupado **0,007414 s** (**1,61 veces** más rápido el no agrupado).
* En 10.000 registros: B+ no agrupado tardó **0,006495 s** y B+ agrupado **0,009359 s** (**1,44 veces** más rápido el no agrupado).
* En 100.000 registros: B+ no agrupado tardó **0,007554 s** frente a **0,010128 s** de B+ agrupado (**1,34 veces** más rápido el no agrupado).

El índice B+ no agrupado superó al agrupado en tiempo de escaneo de rango debido a que recorre la lista enlazada horizontal de hojas recolectando únicamente punteros RID sintéticos de 8 bytes, sin tener que deserializar los 36 bytes de cada registro completo como hace el B+ agrupado.

**Limitación estructural de Extendible Hash:** Extendible Hash registra **NA** en esta prueba porque **no soporta búsquedas por rango por diseño estructural**. La función hash pseudoaleatoria destruye deliberadamente el orden natural de las claves numéricas para distribuirlas uniformemente en los buckets; dos claves consecutivas como 100 y 101 terminan en buckets completamente disjuntos. Esta limitación no constituye un dato faltante ni una falla de implementación, sino una característica matemática intrínseca de los esquemas de dispersión.

#### Espacio en disco y memoria RAM
![](../benchmarks/results/indexes_espacio_disco.png)
![](../benchmarks/results/indexes_espacio_adicional.png)
![](../benchmarks/results/indexes_memoria.png)

El consumo de recursos físicos refleja diferencias marcadas en la arquitectura de cada estructura:
* **Espacio total en disco (B+ Tree)**: En 100.000 registros, tanto B+ agrupado como B+ no agrupado generaron un archivo de **9.437.184 bytes** (~9,00 MB, correspondiente a 2.303 páginas de nodos y 1 de cabecera).
* **Espacio adicional neto**: En B+ agrupado las hojas contienen los datos primarios, por lo que su sobrecosto indexado real es de **5.837.184 bytes** (~5,57 MB) tras restar los 3.600.000 bytes de registros brutos ($100.000 \times 36$ B). En cambio, en B+ no agrupado los **9.437.184 bytes** representan un consumo adicional total que se suma al archivo de almacenamiento primario.
* **Memoria RAM estimada (Extendible Hash)**: Medida mediante `sys.getsizeof` sobre el grafo de objetos en RAM con referencias únicas, el hash consumió **251.051 bytes** (~245 KB) para 1K, **2.504.675 bytes** (~2,39 MB) para 10K y **27.037.259 bytes** (~25,78 MB) para 100K registros. En 100.000 registros, la estructura alcanzó una profundidad global de 12, 4.096 punteros de directorio y 2.081 buckets activos con factor de carga del 75,08% (0,7508) sin generar buckets de desborde.

#### Inserciones y eliminaciones frecuentes
![](../benchmarks/results/indexes_tiempo_actualizaciones.png)

Se ejecutaron 500 ciclos continuos de inserción seguidos de eliminación (1.000 operaciones dinámicas):
* En 1.000 registros: Extendible Hash tardó **0,015140 s**, B+ no agrupado **0,812609 s** y B+ agrupado **1,662218 s**.
* En 10.000 registros: Extendible Hash tardó **0,012707 s**, B+ no agrupado **2,722059 s** y B+ agrupado **5,001173 s**.
* En 100.000 registros: Extendible Hash tardó **0,023630 s**, B+ no agrupado **7,480661 s** y B+ agrupado **10,963724 s**.

Las estructuras B+ exhibieron una degradación sensible con la escala del dataset: B+ no agrupado incrementó su tiempo en **9,21 veces** (de 0,81 s a 7,48 s) y B+ agrupado en **6,60 veces** (de 1,66 s a 10,96 s), debido al mayor número de niveles del árbol, las divisiones/fusiones de páginas y la sincronización a disco. Por el contrario, Extendible Hash mostró una estabilidad excepcional (0,015 s en 1K vs 0,023 s en 100K), absorbiendo mutaciones frecuentes con costo despreciable gracias a sus divisiones locales en RAM sin rebalanceos globales costosos.

#### Resumen y conclusiones de índices

| Técnica | Ventajas | Desventajas | Escenario recomendado |
| :--- | :--- | :--- | :--- |
| **B+ Agrupado** | Resuelve eficientemente igualdad y rangos; registros residen ordenados en las hojas, evitando I/O secundario al storage. | Construcción y splits costosos (mueve registros de 36 bytes); no provee RIDs estables; mayor costo en mutaciones dinámicas. | Tablas ordenadas por clave primaria con consultas de rango masivas y lecturas analíticas continuas. |
| **B+ No Agrupado** | Soporta rangos y ordenamientos; construcción 1,58× más rápida que el agrupado; hojas compactas con solo pares clave-RID. | Requiere I/O adicional para recuperar registros completos desde el storage primario; duplicación de espacio de almacenamiento. | Índices secundarios sobre columnas con filtros de rango (`BETWEEN`, `>`, `<`) o cláusulas `ORDER BY`. |
| **Extendible Hash** | Búsqueda por igualdad ultrarrápida ($O(1)$, ~19× a 30× más veloz que B+); mutaciones dinámicas en memoria sin degradación; divide buckets localmente. | Incapaz de resolver consultas por rango o recorridos ordenados por limitación estructural; requiere residencia en memoria o snapshots. | Índices secundarios para acelerar búsquedas de clave exacta (joins por igualdad, claves de autenticación, catálogos sin rangos). |

### 3.4 Conclusión general de la Parte 1
Los resultados empíricos demuestran que no existe una estructura óptima universal, sino equilibrios de diseño (*trade-offs*) específicos entre costo de escritura, latencia de lectura y consumo de recursos. Para sistemas con **alta tasa de escritura y consultas de punto exacto** (sistemas transaccionales OLTP o ingesta masiva), la arquitectura superior consiste en **Heap File combinado con Extendible Hashing**, combinando inserción en $O(1)$ sin sobrecosto de ordenamiento y búsquedas por clave inmediata sin degradación. Para aplicaciones con **cargas de solo lectura o consultas analíticas con filtros de rango y ordenamiento**, la combinación recomendada es **Heap File con índice B+ Tree No Agrupado**, o bien **Sequential File** si los datos se cargan masivamente de forma preordenada y se someten a reorganizaciones batch periódicas, garantizando escaneos de rango continuos con mínimo costo de I/O.
