# Índices B+

## Agrupado — issue #3

`BPlusTreeClustered(filepath, schema_def, key_field, M=4, page_size=4096)`
guarda **los registros completos en las hojas**, en orden de clave primaria.
`insert(record)` devuelve `False` para una clave repetida; `search(key)` devuelve
el registro o `None`; `delete(key)` devuelve si eliminó un registro.
`range_search(lower, upper)` devuelve registros, con límites inclusivos por
defecto; `include_lower=False` / `include_upper=False` excluyen los extremos.
`scan()` recorre los registros en orden y `iter_range()` produce pares
`(clave, registro)` incrementalmente. `None` representa un límite abierto.

`M` indica el máximo de claves, por lo que un nodo interno tiene hasta `M+1`
hijos. Las hojas no raíz mantienen al menos `ceil(M/2)` entradas y los internos
al menos `floor(M/2)` claves. Los splits propagan separadores; la eliminación
redistribuye entre hermanos o fusiona nodos, reduciendo la raíz si corresponde.
Todas las hojas tienen la misma profundidad y enlaces a la siguiente hoja.

`BPlusTree` conserva la API base `insert(key, payload)`: su modo agrupado guarda
identificadores de páginas de datos y el no agrupado guarda RIDs. La subclase
`BPlusTreeClustered` usa esa misma lógica de árbol con registros en las hojas.

La persistencia usa `struct` en páginas fijas. La cabecera almacena raíz, primera
hoja, cantidad de páginas, `M`, tamaño de página y una firma del schema/formato.
Al reabrir, se recuperan `M` y tamaño de página del archivo; debe proporcionarse
el mismo schema y clave. El formato `BPT2` rechaza archivos del prototipo previo;
esos índices deben reconstruirse a partir de sus datos originales.

Las claves son int64, float finito o strings UTF-8 que caben en el campo. No se
truncan strings ni se admiten NULL/NUL. Los splits y merges mueven registros:
no se prometen RIDs estables para las hojas agrupadas. Las páginas fusionadas
quedan sin referencias y no se reutilizan aún. No hay WAL, recuperación ante
caídas ni coordinación de escritores concurrentes.

Pruebas: `python -m unittest discover -s tests -v`.

## No agrupado — issue #4

`BPlusTreeUnclustered(filepath, key_type="int", order=4, key_size=64,
page_size=4096)` usa la misma estructura y rebalanceo, pero guarda **clave y RID**
en las hojas. `order` es el máximo de claves `M`; `key_size` se usa para strings.
Los RIDs codifican página y slot (31 bits cada uno) y archivo `main`/`aux`.
Admite claves repetidas, incluso si ocupan varias hojas; no repite el mismo par.

- `insert(key, rid)`: devuelve si insertó un par nuevo.
- `search(key)`: lista de todos los RIDs de esa clave.
- `delete(key, rid=None)`: elimina un par o toda la clave y devuelve la cantidad.
- `range_search(lower, upper)`: RIDs del rango; `iter_range` produce pares.
- `iter_ordered(reverse=False)`: RIDs de todos los registros en orden de clave.
- `resolve(rid, storage)`: obtiene el registro real con `storage.get`, o `None`
  si fue eliminado. `search_records(key, storage, key_field=...)` resuelve todos
  los resultados; el campo permite descartar referencias cuyo valor no coincide.
- `bulk_load_from_storage(storage, key_field, replace=True)`: carga los registros
  activos de heap/secuencial. `bulk_load(entries, replace=False)` acepta pares.

Con `replace=True` se construye un archivo temporal y se reemplaza el índice
solo al completar la carga. Un fallo de la fuente conserva el índice anterior.
La carga incremental conserva los pares ya insertados si falla la fuente.
El llamador mantiene abierto el storage y debe sincronizar el índice después
de cambios directos: en particular, los RIDs del secuencial pueden moverse.
Al reabrir debe usar el mismo tipo y tamaño de clave. `key_field` de la fuente
no se persiste: puede proporcionarse a `search_records` o establecerse de nuevo
con `bulk_load_from_storage`.

Para SQL se registra con
`IndexInfo("nombre", "campo", indice, ordered=True)` en `Catalog`. El optimizador
puede usarlo para igualdad, ORDER BY, GROUP BY y joins, según costo. El catálogo
reconstruye el índice después de INSERT/DELETE para actualizar los RIDs.

La rama #4 se basa en la implementación de #3. Integrar primero #3 en main y
después #4 evita duplicar cambios del motor compartido.
