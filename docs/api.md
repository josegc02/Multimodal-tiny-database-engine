# API REST del motor

Base de las aplicaciones de la Parte 5. Recibe SQL por HTTP y responde en JSON.

## Levantarla

```bash
python -m pip install -r requirements.txt -r requirements-api.txt
uvicorn api.main:app --reload          # http://127.0.0.1:8000, documentación en /docs
```

| Variable | Para qué | Por defecto |
| :--- | :--- | :--- |
| `BD2_DATA_DIR` | Carpeta de las tablas e índices | `data/app` |
| `BD2_ARCHIVOS` | Carpetas desde las que `/archivos` sirve imágenes y audios (separadas por `;` en Windows y `:` en Linux) | `datasets`, `fotos` y `BD2_DATA_DIR` |
| `BD2_CORS_ORIGINS` | Orígenes del front web, separados por comas | `http://localhost:5173`, `http://127.0.0.1:5173` |

Los datos **se conservan entre reinicios**: las tablas se crean una vez (con los scripts de carga) y la API las reabre al iniciar.

## Endpoints

| Método y ruta | Qué hace |
| :--- | :--- |
| `GET /salud` | Comprueba que la API está viva |
| `POST /sql` | Ejecuta SQL |
| `GET /tablas` | Lista las tablas con sus columnas e índices |
| `GET /archivos?ruta=...` | Devuelve una imagen o audio guardado en una columna `IMAGE` / `AUDIO` |

### `POST /sql`

Petición:

```json
{"sql": "SELECT nombre, ubicacion FROM tiendas ORDER BY distancia(ubicacion, POINT(-12.12, -77.03)) LIMIT 1"}
```

Respuesta `200`:

```json
{
  "columnas": ["nombre", "ubicacion"],
  "filas": [["Larcomar", {"lat": -12.1318, "lon": -77.03}]],
  "mensaje": null,
  "plan": null,
  "tiempos": {"planificacion": null, "ejecucion": null}
}
```

- `filas` es una lista de listas, en el orden de `columnas`.
- `POINT` llega como `{"lat", "lon"}`; `IMAGE` y `AUDIO`, como su ruta (úsala con `/archivos`).
- `mensaje` trae el resultado de `CREATE`, `INSERT`, `DELETE` y `COPY` (por ejemplo, `"2 registro(s) insertado(s)"`).
- Con `EXPLAIN [ANALYZE]`, `plan` trae las líneas del plan; con `ANALYZE`, `tiempos` trae los segundos.
- Se pueden enviar varias sentencias separadas por `;`. Se responde con el resultado de la última y los mensajes de todas.

Errores `400`:

```json
{"error": "La tabla 'fantasma' no existe"}
```

**Transacciones.** Cada petición es independiente (autocommit). Un script puede usar `BEGIN ... COMMIT` o `ROLLBACK`, pero si termina con la transacción abierta, o falla a mitad, se deshace todo y se responde con error.

### `GET /tablas`

```json
[
  {
    "nombre": "tiendas",
    "almacenamiento": "heap",
    "filas_estimadas": 2,
    "clave_primaria": "id",
    "columnas": [{"nombre": "id", "tipo": "INT"}, {"nombre": "nombre", "tipo": "VARCHAR(20)"},
                 {"nombre": "ubicacion", "tipo": "POINT"}],
    "indices": [{"nombre": "tiendas_pkey", "columna": "id", "metodo": "hash"},
                {"nombre": "tiendas_geo", "columna": "ubicacion", "metodo": "rtree"}]
  }
]
```

- `almacenamiento`: `heap`, `sequential` o `btree`.
- `metodo`: `hash`, `btree`, `rtree`, `spimi`, `hnsw`, `ivf`, `btree agrupado` o `secuencial`.
- `filas_estimadas` sale de las estadísticas del optimizador; puede ir algo atrasado tras muchas escrituras.

### `GET /archivos?ruta=...`

Devuelve el archivo tal cual. Para mostrar una imagen en el front:

```html
<img src="http://127.0.0.1:8000/archivos?ruta=datasets/tienda/img/123.jpg">
```

Solo sirve imágenes y audios dentro de las carpetas de `BD2_ARCHIVOS`: fuera de ellas responde `403`, y si el archivo no existe, `404`.

## Límites

- Atiende **una petición a la vez**, porque el motor tiene una sola sesión SQL. Alcanza para la demo; una consulta lenta hace esperar a las demás.
- Al iniciar, los índices se reconstruyen desde las tablas. Con miles de imágenes, el HNSW puede tardar alrededor de un minuto en estar listo.
- Los endpoints propios de cada aplicación (`/asistente/preguntar` en #98 y `/recomendaciones/{id}` en #101) se agregan sobre esta base.
