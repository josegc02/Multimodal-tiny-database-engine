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
