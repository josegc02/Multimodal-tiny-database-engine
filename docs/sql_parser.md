# Parser SQL

La gramática del dialecto está definida en [sql_grammar.ebnf](sql_grammar.ebnf).
La implementación separa el análisis léxico, el análisis sintáctico y la
representación del resultado:

| Módulo | Responsabilidad |
| --- | --- |
| `engine/query/lexer.py` | Convierte el texto en tokens con posición, línea y columna. |
| `engine/query/parser.py` | Parser descendente recursivo; construye el AST según la precedencia de operadores. |
| `engine/query/ast.py` | Nodos inmutables para sentencias, expresiones, tablas, joins y ordenamiento. |
| `engine/query/errors.py` | Errores léxicos y sintácticos con ubicación y señalamiento del texto. |
| `engine/query/catalog.py` | Registra archivos abiertos e índices y mantiene su vigencia. |
| `engine/query/logical_plan.py` | Valida nombres y agrupaciones y transforma el AST en un plan lógico. |
| `engine/query/expressions.py` | Evalúa expresiones con lógica SQL de tres valores. |
| `engine/query/sql_executor.py` | Ejecuta el plan sobre storage, índices y algoritmos externos. |

## Alcance

- `SELECT`: proyecciones, `*`, `tabla.*`, aliases, `DISTINCT`, joins internos con
  `ON`, `WHERE`, `GROUP BY`, `HAVING`, `ORDER BY`, `LIMIT` y `OFFSET`.
- Expresiones: aritmética, comparaciones, `AND`, `OR`, `NOT`, paréntesis,
  `IS [NOT] NULL`, `[NOT] BETWEEN`, `[NOT] IN` y `[NOT] LIKE`.
- Agregados: `COUNT`, `SUM`, `AVG`, `MIN` y `MAX`, con un argumento y `DISTINCT`
  opcional. `COUNT(*)` es el único agregado que admite un comodín.
- `INSERT INTO ... VALUES`: una o varias filas de literales, con lista opcional
  de columnas. No se admiten expresiones ni subconsultas dentro de `VALUES`.
- `DELETE FROM ...`: con alias y filtro opcionales.
- `CREATE TABLE ...`: columnas `INT`, `FLOAT`, `STR(n)` o `VARCHAR(n)`.
- `CREATE TABLE ... USING HEAP|SEQUENTIAL`: selecciona el storage físico; por
  defecto se usa `HEAP`.
- `CREATE INDEX ... ON ... (...) USING HASH|BTREE`: índices de una columna.
- Transacciones: `BEGIN`, `COMMIT`, `END` y `ROLLBACK`, con `TRANSACTION` opcional.
  `END` se representa como `COMMIT` en el AST.

No se admiten `ALTER`, `DROP`, `UPDATE`, subconsultas, uniones de resultados
(`UNION`), joins externos/cruzados, tablas separadas por comas,
parámetros, funciones de ventana ni funciones arbitrarias. Los nombres de tabla
tienen un componente; las columnas pueden tener uno o dos (`columna` o
`tabla.columna`). Toda entrada fuera del dialecto produce un error.

## Contrato del AST

`parse(sql)` devuelve una sentencia y exige consumir toda la entrada, con un
punto y coma final opcional. `parse_script(sql)` devuelve una tupla de sentencias
separadas por `;`; un script vacío devuelve `()`. Si una sentencia falla, no se
devuelve un resultado parcial. Ninguna de las dos funciones ejecuta SQL.

```python
from engine.query import parse

query = parse("""
    SELECT category, COUNT(*) AS n
    FROM products
    WHERE price >= 10
    GROUP BY category
    ORDER BY n DESC;
""")
print(query.from_table.name)  # products
print(query.to_dict())       # Representación compatible con JSON
```

`CreateTableStatement` conserva el nombre y las definiciones de columnas;
`CreateIndexStatement` conserva el nombre, la tabla, la columna y el método
(`hash` o `btree`). `SelectStatement` conserva proyecciones, fuente, joins, filtro, agrupación,
`HAVING`, orden y límites. `InsertStatement` conserva la tabla, las columnas y
filas de nodos `Literal`. `DeleteStatement` conserva tabla y filtro, mientras
que `TransactionStatement` conserva la acción. Los nodos de expresión retienen
la estructura de operadores, sin convertirlos a código Python ni evaluarlos.

Los identificadores sin comillas se normalizan a minúsculas. Los identificadores
entre comillas dobles conservan mayúsculas, espacios y Unicode. Los strings usan
comillas simples; `''` representa una comilla dentro del valor. La barra invertida
es literal. Los comentarios y los `;` dentro de un string no dividen sentencias.

La precedencia, de menor a mayor, es `OR`, `AND`, `NOT`, predicados/comparaciones,
`+`/`-`, `*`/`/`/`%` y signos unarios. La aritmética binaria asocia a la izquierda.
El `AND` de `BETWEEN` pertenece al predicado. Las comparaciones encadenadas como
`a < b < c` se rechazan; se debe escribir `a < b AND b < c`.

En `OrderByItem`, la dirección predeterminada es `ASC`. `nulls_first=None` indica
que no se especificó `NULLS FIRST/LAST`; el planificador resolverá el valor por
defecto del motor. Los operadores `<>` y `!=` se normalizan a `!=`.

## Validación y conexión con el motor

El parser valida la sintaxis y restricciones estructurales como el ancho de las
filas de `INSERT` o los agregados anidados. `LogicalPlanner` resuelve tablas,
columnas y aliases, verifica las reglas de agrupación y rechaza agregados en
`WHERE` o `ON`. Construye nodos de lectura, filtro, join, agregación, orden,
proyección, límite y modificación.

`Catalog` registra instancias abiertas de `HeapFile` o `SequentialFile`. El
llamador controla su apertura y cierre. Ejemplo, con un storage ya abierto que
contenga las columnas `id`, `category` y `price`:

```python
from engine.query import Catalog, SQLExecutor

catalog = Catalog()
catalog.register_table("products", storage)
executor = SQLExecutor(catalog)
rows = list(executor.execute("SELECT * FROM products WHERE price >= 10"))
print(executor.explain("SELECT * FROM products ORDER BY price"))
```

Se pueden registrar índices con `indexes={"id": index}`. El adaptador
`sql_optimizer.py` conecta el plan SQL con `QueryPlanner`, incorporado desde la
rama `6-algoritmos-externos-sort-group-by-join`. Compara costos estimados de
páginas: igualdad mediante índice o scan; join mediante búsquedas en el índice
derecho o external hash join; orden y agrupación mediante un índice ordenado
compatible o los algoritmos externos. En empates conserva el scan/algoritmo
externo. `explain()` incluye `physical` con algoritmo, costo y motivo para cada
operador elegible; no recorre las tablas. La decisión se vuelve a calcular al
ejecutar para respetar índices invalidados.

El catálogo calcula filas, páginas y cardinalidades al registrar o refrescar una
tabla. Conserva hasta 1024 valores distintos por columna; las cardinalidades
mayores se subestiman. Se pueden proporcionar estimaciones con
`register_table(..., statistics=TableStats(rows, pages, distinct_values))`.
Las escrituras SQL refrescan estas estadísticas. Los costos son aproximaciones:
los filtros intermedios conservan la estimación de entrada y los joins encadenados
usan una cota conservadora, sin materializar datos durante la planificación.

Para índices ordenados se registra un `IndexInfo` con `ordered=True` y un índice
que implemente `iter_ordered(reverse=False)`, además de búsqueda y reconstrucción.
También admite `clustered`, `lookup_pages` y la ubicación de NULLs. El extendible
hash solo ofrece igualdad. `BPlusTreeUnclustered` implementa el contrato ordenado
y se puede registrar con `IndexInfo(..., ordered=True)`; sus RIDs se resuelven
en el storage registrado. Véase [Índices B+](bplus_indexes.md).
Las expresiones calculadas o entradas transformadas usan operadores externos.
Los temporales se serializan con `struct`, sin `pickle`. `BufferConfig` limita
la cantidad lógica de registros del buffer, no los bytes de objetos Python.

`SELECT` devuelve un iterador; si se abandona una lectura antes de agotarla,
se debe llamar a `close()` para liberar temporales. `INSERT` y `DELETE` se
ejecutan al llamar a `execute` y devuelven un iterador con
`{"affected_rows": cantidad}`. Las modificaciones reconstruyen los índices,
incluyendo los RIDs que cambian en archivos secuenciales. Tras modificar el
storage directamente, el llamador debe invalidar o reconstruir sus índices
mediante el `TableBinding` devuelto por `register_table`.

`INSERT` exige todas las columnas y valida el lote completo antes de escribir;
el storage no admite valores `NULL` ni defaults. `DELETE` reúne los RIDs antes
de modificar registros. No hay rollback ante fallos de E/S: una escritura puede
quedar parcialmente aplicada y sus índices se mantienen inválidos hasta su
reconstrucción. El ejecutor admite `SELECT DISTINCT` y `HAVING`; los agregados
con argumento `DISTINCT` y las transacciones solo se reconocen en el parser y
se rechazan durante la planificación.

`SQLLexError` y `SQLParseError` heredan de `SQLError`/`ValueError`. Exponen
`message`, `offset` (desde cero), `line` y `column` (desde uno). El mensaje incluye
la línea original y un indicador `^` donde se detectó el error.

## Pruebas

```bash
python -m unittest discover -s tests -v
```

Las pruebas verifican tokens, escapes, comentarios, ASTs, precedencia, joins,
agregados, scripts, errores con posición, listas extensas y límites de anidamiento.
Las cuatro formas del enunciado (`SELECT WHERE`, `SELECT ORDER BY/GROUP BY`,
`INSERT` y `DELETE`) se ejecutan sobre heap y secuencial. También se comparan
consultas con SQLite y se comprueba el uso real del índice, la actualización de
RIDs, los fallos de escritura y la limpieza de temporales con buffers pequeños.
Las pruebas del optimizador cambian estadísticas y costos para comprobar ambas
rutas de ejecución (índice/externo), filtros residuales, índices inválidos y el
contrato de índices ordenados mediante un índice de prueba.
