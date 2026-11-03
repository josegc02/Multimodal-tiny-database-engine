# PostgreSQL GIN — Parte 3, issue #50

Este setup usa los CSV de [#49](../datasets/text/README.md) sin transformarlos:
`id,url,contenido,categoria,tema`. Cada tamaño tiene una tabla independiente
`texto.noticias_1000`, `texto.noticias_10000` o `texto.noticias_100000`.
El único texto indexado es `contenido`, igual que SPIMI. Las etiquetas de
relevancia no se añaden al vector ni al ranking.

## Inicio reproducible

Desde la raíz del repositorio:

```sh
.venv/bin/python -m pip install -r requirements-text-postgres.txt
docker compose -f postgres_text/docker-compose.yml up -d --wait
# Solo si todavía no existen los datasets:
.venv/bin/python -m benchmarks.generate_text_datasets
.venv/bin/python -m postgres_text.load
.venv/bin/python -m postgres_text.verify
```

La imagen está fijada por digest (PostgreSQL 16.15, Debian bookworm) para
repetir el entorno probado. PostgreSQL se publica solo en `127.0.0.1:5434`, base `texto`, usuario y
clave de desarrollo `bd2`. El proyecto Compose `bd2-texto` y su volumen son
independientes del servicio PostGIS de la Parte 2. El estado se conserva al
detener el servicio:

```sh
docker compose -f postgres_text/docker-compose.yml down
```

Para otro puerto, definir `TEXT_POSTGRES_PORT=5435` al ejecutar Compose y
`TEXT_POSTGRES_DSN=postgresql://bd2:bd2@localhost:5435/texto` para los comandos
Python. También aceptan `--dsn`. En una instalación PostgreSQL existente,
crear una base vacía de pruebas y usar su DSN; `load` inicializa el esquema
automáticamente. El usuario necesita permisos para crear esquemas y tablas.

`load --sizes 1000` permite cargar solo un tamaño. El cargador valida antes
el bundle completo (checksums, tamaños, consultas y qrels), usa COPY FROM
STDIN y crea el GIN después de cargar. Por tamaño, tabla, datos, metadatos,
índice y ANALYZE se confirman juntos. Un fallo revierte ese tamaño; tamaños
anteriores ya confirmados se conservan. Si la tabla existe, se rechaza la
recarga sin reemplazarla. Para reutilizar datos, ejecutar `verify` y `status`.

El volumen Docker conserva los datos; `init.sql` se ejecuta automáticamente
solo en un volumen nuevo. El cliente también puede ejecutarlo de forma
idempotente. No se necesitan PostGIS ni extensiones adicionales.

## Consultas y plan

```sh
.venv/bin/python -m postgres_text.search 'inflación precios alimentos' --size 1000
.venv/bin/python -m postgres_text.search 'banca & digital' --size 1000 --tsquery
.venv/bin/python -m postgres_text.search 'inflación precios alimentos' --size 100000 --explain
.venv/bin/python -m postgres_text.status --size 100000
docker compose -f postgres_text/docker-compose.yml exec -T postgres psql -U bd2 -d texto -v ON_ERROR_STOP=1 < postgres_text/examples.sql
```

La salida de búsqueda son pares `[id, score]`, ordenados por score
descendente y luego ID ascendente. Se devuelven diez por defecto; `--top-k`
permite cambiarlo. Las consultas vacías, sin términos conocidos o solo con
stopwords no producen resultados.

## Decisiones para una comparación válida

La columna `full_text` es `tsvector GENERATED ALWAYS AS
(to_tsvector('pg_catalog.spanish'::regconfig, contenido)) STORED`.
No depende de `default_text_search_config`: insertar o actualizar contenido
recalcula el vector automáticamente. GIN también refleja INSERT, UPDATE y
DELETE. El DDL está en `schema.py`; `init.sql` prepara el namespace y la
tabla de procedencia. `dataset_loads` registra el hash original de cada CSV.

La búsqueda normal tokeniza y une palabras literales con OR (`|`) antes de
llamar a `to_tsquery('spanish', ...)`. Eso conserva la intención de recuperar
candidatos que compartan al menos un término, como el motor. Las consultas
de 6 palabras de #49 incluyen contexto que puede no aparecer en el corpus;
convertirlas silenciosamente a AND cambiaría la tarea. `--tsquery` permite
operadores explícitos para los ejercicios del laboratorio, pero ese modo
no debe mezclarse con el workload OR en la comparación.

PostgreSQL aplica sus propios diccionarios, stopwords y stemming español;
el motor usa su pipeline Snowball y su lista de stopwords. Se comparte texto
original e intención OR, no se garantiza igualdad de lexemas o candidatos.
Las puntuaciones tampoco son equivalentes: `ts_rank(..., 0)` usa el ranking
nativo con normalización 0, no BM25 ni el coseno lnc.ltc. No se eliminan las
posiciones del vector. Los scores de técnicas distintas no se comparan
numéricamente: #51 debe evaluar las listas de IDs contra los mismos qrels.

GIN acelera la búsqueda de candidatos por `@@`; no devuelve por sí mismo
el top-k ordenado por relevancia. PostgreSQL calcula `ts_rank` y ordena los
candidatos. El plan puede elegir Seq Scan para consultas poco selectivas o
tablas pequeñas. `--explain` muestra el plan natural, sin ejecutar ni forzar
el índice. Un test usa `SET LOCAL enable_seqscan=off` exclusivamente para
comprobar disponibilidad del índice; esa configuración no llega al cliente
normal ni debe usarse como resultado de rendimiento.

`load_csv`, `build_index` y `analyze` son operaciones separadas para #51.
El tiempo de cargar incluye construir los tsvector almacenados; el tiempo
de `build_index` solo incluye CREATE INDEX y su commit cuando se usa fuera
de otra transacción. Deben definirse y reportarse esos límites al medir.
Este issue prepara el entorno, no genera la comparación experimental.

## Referencias

Se siguieron el PPT 09 (columna generada, `to_tsvector`, GIN y `to_tsquery`)
y el Laboratorio 10, apartado de noticias (CSV, ranking y revisión del plan).
Se conserva `contenido` como único texto indexado para coincidir con #49,
en lugar de concatenar un título que ese dataset no tiene.

- [PostgreSQL 16: tablas e índices de texto](https://www.postgresql.org/docs/16/textsearch-tables.html).
- [PostgreSQL 16: consultas y ranking](https://www.postgresql.org/docs/16/textsearch-controls.html).
