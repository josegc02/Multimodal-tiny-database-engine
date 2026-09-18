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
