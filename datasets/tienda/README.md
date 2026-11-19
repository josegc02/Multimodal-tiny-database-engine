# Datos de la tienda — issue #100

La opción B usa una categoría de Amazon Reviews 2023 (`Video_Games`) y una
instantánea de tiendas reales de Lima tomada de OpenStreetMap. El stock se
genera con una semilla fija: **no representa inventario real**.

## Reproducir el dataset

Ejecutar desde la raíz del repositorio, con `requirements.txt` instalado y
acceso a Internet para los tres primeros pasos:

```sh
python -m tienda.amazon seleccionar --cantidad 8000
python -m tienda.imagenes --hilos 8
python -m tienda.amazon compras
python -m tienda.carga preparar --semilla 100
python -m tienda.carga cargar --datos data/app
```

La selección elige los candidatos con más reseñas que tengan precio,
descripción (al menos 15 palabras) e imagen. El paso de imágenes descarta los
archivos que no se decodifican, miden menos de 100 px por lado o carecen de
puntos SIFT suficientes. Si quedan menos de 5 000 productos, repetir la
selección con una `--cantidad` mayor (máximo 20 000) y ejecutar de nuevo los
pasos siguientes. `compras` usa solo reseñas con `verified_purchase=true` de
usuarios que compraron al menos dos productos del catálogo.

`preparar` comprueba que haya entre 5 000 y 10 000 productos válidos,
verifica las referencias de compras y genera `stock.csv`, `cargar_motor.sql`
y `metadata.json` con conteos, semilla y SHA-256. Cada producto se asigna a
una, dos o tres tiendas elegidas con semilla fija; cada par recibe 1–20
unidades. El orden de los CSV de entrada no afecta al stock generado.

`cargar` crea las tablas e índices en la carpeta indicada. Rechaza una carpeta
que ya contenga las tablas de la tienda. Para repetir la carga, usar **otra**
carpeta de datos; el script no borra datos existentes. La ruta de cada imagen
en `productos.csv` se genera para la máquina que ejecutó la descarga, así que
hay que regenerar ese CSV al mover el dataset a otro equipo.

| Archivo | Versionado | Contenido |
|---|---|---|
| `tiendas_lima.csv`, `tiendas_lima.json` | Sí | Instantánea OSM y consulta/fecha de origen |
| `raw/` | No | Metadata y reseñas comprimidas de Amazon |
| `imagenes/` | No | Fotos descargadas de productos |
| `generated/productos_candidatos.csv` | No | Selección preliminar |
| `generated/productos.csv` | No | Catálogo con imágenes válidas |
| `generated/compras.csv` | No | Compras verificadas |
| `generated/stock.csv` | No | Stock sintético reproducible |
| `generated/cargar_motor.sql`, `generated/metadata.json` | No | Carga e integridad |

## Esquema para el issue #101

- `productos(id, asin, titulo, descripcion, precio, rating, num_resenas,
  marca, categoria, url_imagen, imagen)`; `imagen` es `IMAGE`.
- `compras(id, usuario, producto_id, rating, fecha)`; `producto_id` referencia
  a `productos.id`.
- `tiendas(id, osm_id, nombre, tipo, distrito, direccion, ubicacion)`;
  `ubicacion` es `POINT(lat, lon)`.
- `stock(id, tienda_id, producto_id, unidades)`; ambas referencias tienen
  clave foránea.

Las cuatro claves primarias `id` usan el Hash implícito del motor. Los índices
adicionales son B+ en `productos.precio`, SPIMI inglés en
`productos.descripcion`, HNSW coseno en `productos.imagen`, R-Tree en
`tiendas.ubicacion` y Hash en `compras.usuario`. El motor crea también índices
para las claves foráneas. Esos nombres de tablas y columnas son el contrato
de datos de la API de recomendaciones.

## Fuentes y licencias

- Metadata, reseñas e imágenes: [Amazon Reviews 2023 de McAuley Lab,
  UCSD](https://amazon-reviews-2023.github.io/), categoría `Video_Games`.
  El equipo del dataset indica que no puede asignarle una licencia y que lo
  ofrece principalmente para investigación: [respuesta sobre la licencia
  del dataset](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/discussions/1).
  Por eso los datos y fotos descargados no se versionan aquí.
- Ubicaciones: [OpenStreetMap](https://www.openstreetmap.org/copyright),
  © OpenStreetMap contributors, licencia ODbL 1.0. La instantánea versionada
  conserva la consulta Overpass y su fecha en `tiendas_lima.json`. Si se
  muestran las tiendas en la web, debe mantenerse visible esa atribución.
- Stock: generado por este proyecto; es sintético y no procede de Amazon ni
  de OpenStreetMap.

Prueba local sin red: `python -m pytest -q tests/test_tienda_carga.py`.
