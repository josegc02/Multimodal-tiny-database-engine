# Parte 2: Base de Datos Espacial

Implementados: geometría, métricas, R-Tree y consultas espaciales hasta #23.
El mapa Leaflet (#24) está integrado. Datasets de entrega (#25), comparación con
PostGIS (#26) y benchmarks (#27) siguen pendientes. Contratos, criterios
verificados y ejemplos SQL en [consultas_espaciales.md](consultas_espaciales.md).

## Qué pide el enunciado

- **Índice R-Tree** para puntos 2D (latitud, longitud) con:
  - consultas por rango ("tiendas en un radio de 5 km");
  - k-NN ("las 10 gasolineras más cercanas");
  - intersección con polígonos ("sucursales dentro de un distrito").
- **Métricas Euclidiana y geodésica (Haversine).**
- **Panel de mapa** interactivo con los resultados resaltados.
- **Extensión SQL**, por ejemplo:
  ```sql
  SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;
  SELECT * FROM restaurantes ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10;
  ```
- **Comparación experimental** de Secuencial vs R-Tree vs GiST (PostgreSQL):
  - consultas: radio de 1, 5 y 10 km, y k-NN con k = 10, 50 y 100;
  - datasets: 1.000, 10.000 y 100.000 puntos;
  - mediciones: construcción, consulta (promedio de 100) y memoria/disco.

## Estructura y issues

| Archivo | Contenido | Issue |
| :--- | :--- | :---: |
| `engine/spatial/geometry.py` | `Point`, `MBR` (área, unión, enlargement, intersección) y `Polygon` (MBR, ray casting, GeoJSON) | #18, #22 |
| `engine/spatial/distance.py` | Euclidiana, Haversine, MINDIST punto-MBR y radio → MBR | #19 |
| `engine/indexes/rtree.py` | R-Tree en disco: inserción, split, eliminación, rango, k-NN y polígono | #18, #20, #21, #22 |
| `engine/query/` (lexer, parser, ast, catalog, optimizer, explain) | Tipo `POINT`, `distancia(...)`, `ORDER BY distancia LIMIT k`, polígonos, `CREATE INDEX ... USING RTREE`, plan de ejecución | #23 |
| `frontend/panel_mapa.py` | Panel de mapa (puntos, resultados, radio y polígono) | #24 |
| `benchmarks/generate_spatial_datasets.py`, `datasets/spatial/` | Puntos de 1K/10K/100K y polígonos de distritos | #25 |
| `postgis/` | PostgreSQL + PostGIS con Docker, esquema y consultas GiST equivalentes | #26 |
| `benchmarks/bench_spatial.py` | Benchmark Secuencial vs R-Tree vs GiST | #27 |
| `tests/spatial/` | Pruebas de geometría, métricas, R-Tree y SQL espacial | todos |

## Orden sugerido

1. **#19 Métricas** y la parte de geometría de **#18**: son la base de todo lo demás y se prueban solas.
2. **#18 R-Tree** (inserción, split, persistencia) y **#25 datasets**, en paralelo.
3. **#20 rango**, **#21 k-NN** y **#22 polígonos**, comparando siempre contra la búsqueda secuencial (fuerza bruta).
4. **#23 SQL espacial**, que integra el R-Tree al catálogo y al optimizador.
5. **#24 mapa** y **#26 PostGIS**, en paralelo.
6. **#27 benchmark** e informe.

## Geometría y métricas (#18 y #19)

- **Orden de coordenadas:** `POINT(lat, lon)`, como el ejemplo del enunciado. PostGIS y GeoJSON usan `(lon, lat)`, así que hay que invertir el orden al cargar datos y al comparar con GiST.
- **Validación:** `Point` y `MBR` rechazan coordenadas fuera de rango o no finitas, y un `MBR` con mínimos mayores que sus máximos. Un `MBR` no cruza el antimeridiano.
- **`MBR`** (`engine/spatial/geometry.py`): área, semiperímetro (*margin*), unión, *enlargement*, intersección, área de solapamiento (*overlap*) y contención de un punto (incluye el borde).
- **Las dos métricas devuelven metros**, así `distancia(...) < 5000` significa 5 km con cualquiera de ellas (`engine/spatial/distance.py`):
  - **Haversine:** gran círculo sobre una esfera de radio 6.371.008,8 m. Entre Lima y Cusco da 574,6 km.
  - **Euclidiana:** trata (lat, lon) como un plano y convierte grados a metros con un factor fijo (111.195 m por grado). Es exacta en dirección norte-sur y sobreestima en dirección este-oeste por 1/cos(lat).

  | Caso | Haversine | Euclidiana | Diferencia |
  | :--- | ---: | ---: | ---: |
  | Lima - Cusco | 574,579 km | 588,028 km | +2,34% |
  | 5 km al norte de Lima | 5,000 km | 5,000 km | 0% |
  | 5 km al este de Lima | 5,000 km | 5,113 km | +2,25% |

  El error este-oeste depende solo de la latitud: 0% en el ecuador, 2,2% en Lima (12° S), 41% a 45° y 100% a 60°. Para datos de Lima la Euclidiana es una aproximación razonable y más barata; lejos del ecuador conviene Haversine.
- **MINDIST punto-MBR:** es la cota inferior que usa el R-Tree para podar.
  - **Euclidiana:** se acota cada coordenada al rectángulo.
  - **Haversine:**
    - si el punto está dentro de la franja de longitudes, se mide sobre su mismo meridiano;
    - si no, sobre el meridiano del borde más próximo (considerando el antimeridiano), en la latitud de menor distancia o en un extremo del borde.
  - Los tests verifican que nunca supera la distancia real a un punto del rectángulo y que es ajustada.
- **Radio → MBR (filtro grueso):** rectángulo que contiene el círculo, con la latitud ±r/R y la longitud ensanchada según la latitud. Si toca un polo o cruza el antimeridiano devuelve la franja completa de longitudes. Agrega un margen de 10⁻⁹ grados (≈0,1 mm) para que el redondeo no descarte puntos del borde.

## R-Tree (#18)

`engine/indexes/rtree.py` implementa el R-Tree de Guttman en disco:

- **Páginas de 4096 B**, una por nodo; la página 0 es la cabecera (raíz, altura, entradas y lista de páginas libres).
- **Capacidad según la página:**

  | Nodo | Entrada | Bytes | M |
  | :--- | :--- | ---: | ---: |
  | Hoja | (lat, lon, RID) | 23 | 177 |
  | Interno | (MBR, página del hijo) | 36 | 113 |

  El mínimo es m = ⌈0,4·M⌉. Para las pruebas se puede fijar un M chico (`max_entries`).
- **Inserción:**
  - ChooseLeaf baja por el hijo cuyo MBR menos crece (desempate: menor área).
  - Si un nodo se pasa de M entradas, se divide con el **split cuadrático**: elige como semillas el par que más área desperdicia juntas y reparte el resto según qué grupo crece menos.
  - Las áreas empatan en 0 cuando los puntos están alineados; ahí desempata por semiperímetro.
  - Los MBRs se ajustan hacia la raíz; si la raíz se divide, el árbol crece un nivel.
- **Eliminación:** CondenseTree.
  - Los nodos que quedan con menos de m entradas se quitan y sus entradas se reinsertan en su mismo nivel.
  - Si la raíz queda con un solo hijo, el hijo pasa a ser la raíz.
  - Las páginas liberadas se reutilizan.
- **Búsqueda por rectángulo:** `search_mbr` cuenta en `last_stats` los nodos y hojas visitados, para el plan de ejecución y los benchmarks.
- **Rendimiento:** 100.000 puntos de Lima se insertan en ~106 s (~1 ms por inserción, el mismo orden que el B+ agrupado). El árbol queda con altura 3, 831 nodos y hojas llenas al 69%. Una ventana de 59 puntos visita 47 de los 831 nodos.
- **Pruebas** (`tests/indexes/test_rtree.py`): después de cada operación verifican altura balanceada, ocupación entre m y M, MBRs exactos en cada padre y que ninguna página se pierda ni se duplique. También comparan las búsquedas con fuerza bruta y cubren puntos repetidos y alineados, persistencia y reutilización de páginas.

## Decisiones implementadas y pendientes
- **Métrica SQL (#23):** ambas formas están implementadas: `USING HAVERSINE | EUCLIDEAN`
  al final de SELECT y tercer argumento explícito en `distancia`, que tiene prioridad.
- **Polígonos SQL (#23):** `WITHIN(col, POLYGON((lat, lon), ...))`, con borde incluido.
  Los distritos GeoJSON se cargan con `load_districts` en Python.
- **Tipo `POINT`:** dos `float` de 8 bytes en el registro (16 bytes por punto).
- **Construcción masiva del R-Tree (opcional):** *bulk loading* STR acelera la construcción frente a insertar punto por punto. Decidir si se agrega para el benchmark (#27).
- **Mapa (#24):**
  - Opción 1: `tkintermapview`, un widget Tk con OpenStreetMap integrado en la ventana actual.
  - Opción 2: Leaflet en el navegador, con un HTML generado o un endpoint local.
- **Dependencias nuevas:**
  - `psycopg[binary]`, para el benchmark contra PostGIS;
  - posiblemente `tkintermapview`.
  - Se agregan a `requirements.txt` cuando se usen. La CI no levanta PostGIS, así que el benchmark debe poder correr sin él (`--sin-postgis`).

## PostgreSQL + PostGIS

```bash
docker compose -f postgis/docker-compose.yml up -d     # puerto 5433, usuario/clave bd2/bd2, base "espacial"
docker compose -f postgis/docker-compose.yml down -v    # detener y borrar los datos
```

`postgis/init.sql` crea la extensión, las tablas `puntos` (`geography`, distancias en metros) y `distritos`, y deja comentadas las consultas equivalentes:
- `ST_DWithin`, para el rango;
- `ORDER BY <-> LIMIT k`, para k-NN;
- `ST_Within`, para la intersección con polígonos.
