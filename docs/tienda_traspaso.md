# Opción B (tienda): estado y traspaso

Estado al 20 de noviembre de 2026, con todo fusionado en `main` (#113, #116, #117, #118, #120).

## Qué hay

| Parte | Dónde | Estado |
|---|---|---|
| Datos (Amazon Reviews 2023, Video Games) | `tienda/amazon.py`, `tienda/imagenes.py`, `tienda/categorias.py`, `datasets/tienda/README.md` | 7,994 productos limpios, 718 mil compras (usuarios de 2 a 20), 623 tiendas de Lima (OpenStreetMap), stock generado (semilla 100) |
| Carga en el motor | `tienda/carga.py` | Tablas `productos`, `tiendas`, `compras`, `stock` con hash, B+, SPIMI, HNSW y R-Tree |
| Recomendaciones | `tienda/recomendaciones.py`, `api/tienda.py` | 5 señales (compras, imagen MobileNet o SIFT, texto BM25, categoría, consola), fusión RRF, sin duplicados, caché de compras |
| Extractor preentrenado | `engine/features/image/mobilenet.py`, `tienda/indice_imagen.py` | MobileNetV2 ONNX (`models/mobilenetv2-12.onnx`, no está en git) |
| Optimizador del motor | `engine/query/logical_plan.py`, `sql_optimizer.py`, `catalog.py` | Pushdown de selección en JOIN y valores distintos con KMV ("también compraron": 27.7 s → 18 ms) |
| Front | `web/tienda.html`, `web/src/tienda/` | "Partida": catálogo, ficha con mapa, recomendaciones explicadas con pesos en vivo |
| Mediciones | `benchmarks/tienda/` (`medir.py`, `hnsw.py`, `hnsw_escala.py`, `README.md`) | Ver "Cifras" abajo |

## Levantar la tienda

```bash
# una sola vez (≈ 40 min; necesita internet para reseñas e imágenes)
python -m tienda.amazon seleccionar --cantidad 8000
python -m tienda.imagenes --hilos 8
python -m tienda.amazon compras
python -m tienda.carga preparar --semilla 100
python -m tienda.carga cargar --datos data/app     # falla si data/app ya tiene tablas de la tienda
python -m tienda.indice_imagen --datos data/app      # precalcula MobileNet

# cada vez
uvicorn api.main:app                                 # ≈ 6 min en arrancar con la tienda completa
cd web && npm install && npm run dev                 # http://localhost:5173/tienda.html
```

- **La API tarda ~6 minutos en arrancar** (reconstruye los índices: el hash de `compras.usuario` y la tabla `compras` se llevan ~4 min) y el índice MobileNet se arma en segundo plano ~50 s más. **Levantarla 7–10 minutos antes de la demo** y no reiniciarla. Después, una recomendación tarda ~0.2–0.6 s.
- Para recargar la tienda sobre un `data/app` que ya la tiene: hay que quitar sus tablas (no hay `DROP` usado en la carga). Lo más simple es restaurar `data/app` con solo el asistente (`catalogo.json`, `papers.*`, `fragmentos*`) y conservar la carpeta `data/app/mobilenet/` (caché de vectores por imagen).
- Enlace útil para la demo: `tienda.html#/p/<id>/explicar` abre una ficha con la explicación ya visible.

## Cifras (para el informe)

En `benchmarks/tienda/README.md`, medidas en consultas de prueba separadas de las de validación, con IC 95 %:

| | Antes de los PRs | La app |
|---|---:|---:|
| Recomendados del mismo tipo de producto | 45.7 % | **69.1 %** |
| Recupera lo que el usuario compró después | 6.7 % | **10.6 %** |
| Misma consola | 51.9 % | **92.7 %** |
| Listas con duplicados | 42 % | **0 %** |
| "También compraron" (latencia) | 27.7 s | **18 ms** |

También están: la ablación (qué aporta cada cambio), HNSW frente a búsqueda exacta (recall 0.93 sin cambiar el acierto; se cruzan entre 8k y 25k productos) y el EXPLAIN antes y después del optimizador (`docs/sql_parser.md`).

## Lo que falta (en orden de prioridad)

1. **Búsqueda en español.** Hoy BM25 busca sobre descripciones en inglés: "mando inalámbrico" o "audífonos" no encuentran nada, y es lo primero que alguien prueba en una tienda de Lima. Propuesta: lo mismo que en el asistente (`api/asistente.py`, `cognados`) más un diccionario corto de términos de la tienda (mando → controller, audífonos → headset, consola → console, funda → case, cargador → charger, teclado → keyboard, juego → game). Aplicarlo en `GET /catalogo` antes del `MATCH`, y medirlo con ~20 búsquedas en español.
2. **Multiplataforma en consolas clásicas.** `tienda/categorias.normalizar` corrige la consola solo si el título nombra una. Un producto que nombra varias y que Amazon dejó en una consola vieja queda mal (p. ej. Turtle Beach Recon 50, "Xbox Series X/S, Xbox One, PS5…", en "PlayStation" de 1994). Regla propuesta: si la ruta es de "Legacy Systems" y el título solo nombra consolas actuales, usar la primera que nombra. Agregar la prueba en `tests/test_tienda_categorias.py` y regenerar el catálogo.
3. **Recargar `data/app` y volver a medir.** El último ajuste (juegos de mesa fuera) cambió 6 productos que la carga actual de esta PC no tiene; `python -m benchmarks.tienda.medir` actualiza `resultados.json` (las cachés están en `datasets/tienda/benchmark/`; si cambia el catálogo, borrar `bm25.json` y `resenas.csv`, y los `.npy` se reordenan por ASIN).
4. **Cerrar el issue #103** (todo lo pedido está en #120; marcar sus casillas).
5. **Informe (#104) y presentación (#105)**: usar las cifras de arriba y la tabla de limitaciones del dataset de `datasets/tienda/README.md`.

Opcionales: arranque más rápido (cargar el hash extensible en bloque en vez de fila por fila; no revalidar claves al reabrir una tabla), filtrar las tiendas de OpenStreetMap por tipo, y precalcular "también compraron" de los 100 productos más comprados al arrancar.

## Decisiones que conviene no deshacer sin medir

- **Pesos por defecto** (`api/tienda.py`): compras 1, imagen 0.5, texto 1, categoría 0.25, consola 0.5, fusión RRF, 101 candidatos, sin duplicados. Se eligieron en validación; en el catálogo limpio empatan con la alternativa de la grilla (0.991 frente a 0.998) y ganan en prueba.
- **Compras**: solo usuarios con 2 a 20 compras y pares a 30 días o menos. Los usuarios con muchas compras eran ruido (5.8 % → 9.5 % de recall solo con esa señal).
- **El peso de consola se elige con tipo y comportamiento**, nunca con "misma consola" (usa la misma regex que la señal: sería circular).
- **SIFT sigue disponible** (`vector_imagen=sift`): lo pide la Parte 4. No se reentrenó su vocabulario con fotos de la tienda porque cambiaría las cifras de la Parte 4.
- **Catálogo sin búsqueda en orden de carga** (no `ORDER BY id`): ordenar las 7,994 filas para mostrar 24 tardaba 1.5 s.
- **Dos apps en `web/`**: el asistente (`index.html`) y la tienda (`tienda.html`) tienen armazón propio y comparten `src/api.js`.

## Limitaciones del dataset (y qué arregla el proyecto)

- **Arreglado en el dato**: productos que no son videojuegos (libros, películas, juegos de mesa), rutas promocionales, consola de la ruta contradicha por el título (`tienda/categorias.py`).
- **Compensado en la app**: duplicados (se quitan de las recomendaciones, no del catálogo), categorías ruidosas (la señal pesa poco), compras aproximadas con reseñas verificadas, títulos largos (título corto en la interfaz).
- **Sin arreglar**: multiplataforma mal ubicados, descripciones de marketing, sesgo hacia productos viejos (se eligieron los más reseñados), precios de EE. UU. en 2023, stock generado, búsqueda solo en inglés.
