# Exactitud de las recomendaciones de la tienda

Mide qué tan buenas son las 10 recomendaciones de `GET /recomendaciones/{id}` sobre el
catálogo real de la tienda: 7,995 productos de Amazon Reviews 2023 (Video_Games) con
sus fotos y 1.94 millones de compras verificadas.

```bash
python -m benchmarks.tienda.medir     # escribe benchmarks/tienda/resultados.json
```

Requiere `tienda.amazon seleccionar`, `tienda.imagenes` y `tienda.amazon compras` (que
descarga las reseñas). Las cachés (vectores, BM25, reseñas filtradas) quedan en
`datasets/tienda/benchmark/`; sin ellas, extraer SIFT y MobileNet tarda cerca de una hora.

## Dos métricas

Cada una favorece a una señal distinta, así que la configuración final debe **no
perder en ninguna** de las dos.

1. **Tipo** (P@10): fracción de los 10 recomendados del mismo tipo de producto que la
   consulta. Las categorías de Amazon tienen demasiado ruido para servir de etiqueta
   (el mismo mouse aparece como "Gaming Mice", "Accessories" o "PC"), así que el tipo
   sale del título con reglas: juego, mando, audífonos, cargador o cable, mouse,
   estuche, teclado, soporte, mousepad o skin (83 % del catálogo etiquetado).
   **Favorece al texto**, que también sale del producto.
2. **Comportamiento** (recall@10): de los productos que el mismo usuario compró **a
   30 días o menos** de la consulta, cuántos recomienda la app. Se separa por tiempo:
   la señal de compras se construye solo con compras anteriores al corte (7 de agosto
   de 2021, percentil 80) y se evalúa con las posteriores. Solo cuentan usuarios con
   20 compras o menos en el periodo evaluado. Cobertura: 5,680 de 7,995 productos
   (71 %) tienen al menos un objetivo. **Favorece a la señal de compras**.

Línea base "más populares" (siempre los 10 más comprados): 8.3 % de tipo y **2.9 %**
de comportamiento. La métrica de comportamiento no está midiendo popularidad.

## Protocolo

- **Validación**: 281 consultas de tipo y 800 de comportamiento. Ahí se elige todo.
- **Prueba**: 505 y 800 consultas distintas. Ahí se reporta, sin volver a elegir.
- **Regla de selección**, fijada antes de medir: gana la configuración con mayor
  promedio de (métrica ÷ mejor valor de esa métrica en la etapa).
- **Grilla por etapas** para no sobreajustar la validación:
  1. fusión (máximo o RRF) y señal de compras (la de antes o filtrada);
  2. candidatos por señal (51 o 101);
  3. pesos: compras 0 a 2, imagen 0.25 o 0.5, categoría 0, 0.25 o 1 (texto en 1).
- IC 95 % por bootstrap pareado (5,000 remuestreos).
- Imagen: búsqueda exacta por coseno (sin el error del HNSW). Texto: `MATCH ... USING
  BM25` en nuestro motor (SPIMI en inglés). Fusión y bono de categoría como
  `tienda.recomendaciones.fusionar`.

## Resultados (prueba)

| Configuración | Tipo | Comportamiento | Misma consola | Listas con duplicados |
|---|---:|---:|---:|---:|
| Antes: texto + SIFT, pesos 1,1,1, compras de antes | 47.1 % [44.3, 49.9] | 6.2 % [5.3, 7.2] | 53.5 % | 41 % |
| #117 inicial: MobileNet 0.25 + categoría 0.25 | 64.7 % [61.9, 67.6] | 8.9 % [7.7, 10.1] | 72.1 % | 41 % |
| Elegida: RRF, 101 candidatos, compras filtradas, pesos 1/0.5/1, categoría 0.25 | 70.9 % [68.1, 73.5] | 10.2 % [8.9, 11.5] | 75.0 % | 42 % |
| Elegida + solo sin duplicados | 69.9 % [67.2, 72.6] | 10.3 % [9.1, 11.7] | 74.4 % | **0 %** |
| Elegida + solo misma plataforma 0.5 | 70.9 % [68.1, 73.6] | 10.4 % [9.1, 11.7] | 93.1 % | 40 % |
| **Final: sin duplicados + misma plataforma 0.5** | **70.0 %** [67.2, 72.7] | **10.5 %** [9.3, 11.8] | **93.2 %** | **0 %** |

Compras filtradas: solo usuarios con 2 a 20 compras y solo pares a 30 días o menos.

- **Duplicados**: el 42 % de las listas traía el mismo producto con otro id (otro
  color, otra edición, otro vendedor, el mismo juego en otra consola). Se descartan
  los recomendados con la misma clave de título (primeras 6 palabras) o con imagen
  casi idéntica (coseno MobileNet > 0.98), frente al consultado o a uno ya elegido,
  y se rellena con el siguiente candidato. El tipo baja un punto porque los
  duplicados siempre eran del mismo tipo; el comportamiento no cambia.
  **Revisión manual de 30 pares descartados al azar**: 24 eran el mismo producto
  (relistado, importado, otro color o edición), 4 el mismo juego en otra consola
  (conviene quitarlos: con la señal de plataforma queda el de la consola correcta) y
  2 productos distintos (7 %: una funda eXtremeRate para PS4 frente a la de Xbox, y
  dos mandos genéricos con fotos casi iguales). Exigir título **y** imagen perdería
  muchos duplicados reales, cuyas fotos difieren (otro color: coseno 0.6–0.85).
- **Misma plataforma**: la consola sale de la categoría y del título (PS5, PS4,
  Xbox One, Series, Switch, 3DS, Wii, PC, VR, Sega...). Es un bono como el de la
  categoría: solo si el consultado tiene una sola consola, y un producto
  multiplataforma o sin consola no se castiga. El peso (0.5) se eligió en validación
  con las mismas dos métricas de antes; "misma consola" es solo un control, porque
  la señal y esa métrica usan la misma regex y elegir con ella la subiría por
  construcción (con 1.0 llegaba a 98 %, con menos tipo). La plataforma sola no mueve
  el tipo y sube un poco el comportamiento.
  **Revisión manual de la regex en 30 productos** (15 al azar y 15 con títulos como
  "compatible with PS4/PS5"): 25 correctos; 4 errores dejan al producto como
  multiplataforma (accesorios de Quest que Amazon clasifica en PC, una funda de
  Switch en la categoría DS) y no dan bono; solo 1 da un bono equivocado (un mando
  de Android clasificado en Mac).
- "Misma consola" se mide sobre las consultas con una sola plataforma (74 % del
  catálogo).

### Qué aporta cada cambio (sobre #117 inicial)

| Cambio | Tipo | Comportamiento |
|---|---:|---:|
| Solo usuarios con 2 a 20 compras | −0.2 (n. s.) | **+1.6** [+0.8, +2.4] |
| Solo ventana de 30 días | **+2.5** [+1.0, +3.9] | +0.3 (n. s.) |
| Solo RRF con pesos 1/0.5/1/0.25 | **+6.1** [+4.7, +7.6] | −0.4 (n. s.) |
| RRF + usuarios + ventana, 51 candidatos | +5.7 | +0.7 (justo) |
| Todo, 101 candidatos (elegida) | +6.1 | +1.3 |

- **Usuarios con muchas compras eran ruido**: alguien con 80 compras conecta miles de
  pares sin relación. Antes, `compras.csv` priorizaba justo a esos usuarios.
- **La ventana no infla la métrica de comportamiento** (+0.3, aunque la métrica usa la
  misma ventana): mejora el tipo al quitar pares comprados con años de diferencia.
- **RRF** no depende de la escala de cada señal (BM25 no tiene tope; los cosenos de
  MobileNet están todos entre 0.6 y 0.9). Los empates se ordenan por id, que en la
  tienda va de más a menos comprado; con posiciones compartidas en los empates baja a
  69.7 % y 9.8 %.
- **Subir el peso de compras** sube el comportamiento y baja el tipo (compras trae
  complementarios): con peso 2, 12 % y 47 %.

## Latencia de la señal de compras

Con las 714 mil compras filtradas (antes eran 100 mil), la consulta de "también
compraron" es un self-JOIN en nuestro motor. Necesita las dos correcciones al
optimizador del PR #118 (en un PR aparte porque afectan a todas las consultas):

| Versión del motor | Plan | Mediana | Máximo (producto más comprado) |
|---|---|---:|---:|
| Antes | Hash join de toda la tabla consigo misma, filtro al final | 27.7 s | 39 s |
| **Pushdown de selección + valores distintos con KMV** | Index scan en `a.producto_id`, *index nested loop* en `usuario` | **18 ms** | **632 ms** |

El JOIN del motor devuelve los mismos pares que el cálculo en Python en 20 de 20
productos. Sin #118, estas recomendaciones son correctas pero lentas.

## HNSW frente a búsqueda exacta

`python -m benchmarks.tienda.hnsw` (escribe `hnsw.json`): el HNSW del motor
(`engine/indexes/hnsw.py`) sobre los 7,995 productos, 500 consultas, contra la
búsqueda exacta por coseno. La app usa **M=8, ef_construction=50** y en
recomendaciones busca **k=102 con ef_search=102** (en negrita).

| Vector | M / ef_construction | Construcción | k | ef_search | Recall@k | ms/consulta | Nodos visitados | P@10 de tipo |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| MobileNet (1280 dim.) | 8 / 50 | 63 s | 10 | 10 | 0.884 | 3.2 | 142 (2 %) | 72.6 % |
| | | | 10 | 50 | 0.969 | 8.3 | 368 (5 %) | 72.8 % |
| | | | **102** | **102** | **0.931** | **15.6** | **616 (8 %)** | **72.6 %** |
| | | | 102 | 400 | 0.985 | 30.4 | 1,589 (20 %) | 72.7 % |
| | 16 / 100 | 76 s | 10 | 50 | 0.991 | 4.6 | 553 (7 %) | 72.7 % |
| | | | 102 | 102 | 0.972 | 10.1 | 907 (11 %) | 72.7 % |
| SIFT + BoVW (1024 dim.) | 8 / 50 | 38 s | 10 | 10 | 0.663 | 1.5 | 176 (2 %) | 55.5 % |
| | | | 10 | 50 | 0.846 | 3.8 | 464 (6 %) | 56.3 % |
| | | | **102** | **102** | **0.811** | **6.9** | **767 (10 %)** | **56.8 %** |
| | | | 102 | 400 | 0.951 | 20.1 | 1,831 (23 %) | 56.6 % |
| | 16 / 100 | 72 s | 102 | 102 | 0.913 | 10.5 | 1,210 (15 %) | 56.8 % |

Búsqueda exacta: P@10 de tipo 72.6 % (MobileNet) y 56.7 % (SIFT); 4.3 y 3.7 ms
vectorizada con numpy; 36.9 y 20.0 ms fila por fila, como un recorrido secuencial
del motor.

- **La aproximación no cambia la recomendación**: con la configuración de la app,
  el HNSW pierde el 7 % de los vecinos exactos de MobileNet (19 % en SIFT), pero el
  acierto de tipo es el mismo que con la búsqueda exacta. Los vecinos que se
  pierden son casi tan parecidos como los que encuentra.
- **SIFT necesita más ef_search que MobileNet** para el mismo recall: sus
  similitudes están más juntas (todas las fotos se parecen un poco), y el grafo
  distingue peor a los vecinos.
- **Con 8 mil productos, la búsqueda exacta vectorizada (4 ms) es más rápida que
  nuestro HNSW en Python puro** (16 ms): el HNSW gana frente a un recorrido fila por
  fila (37 ms) y escala mejor, porque solo visita el 8 % de los nodos; la búsqueda
  exacta crece en proporción al catálogo.
- M=16 da más recall con el mismo ef_search a cambio de una construcción más larga.
  Para la recomendación no hace falta: el acierto ya es el de la búsqueda exacta.
- Los tiempos varían entre corridas por la carga de la máquina (la configuración de la app midió 9.8 ms en otra corrida); el
  recall y los nodos visitados son deterministas (semilla 42).

### Según el tamaño del catálogo

`python -m benchmarks.tienda.hnsw_escala` (escribe `hnsw_escala.json`): los 7,995
vectores MobileNet reales más copias con ruido hasta 25k y 50k. El ruido está
calibrado para que cada copia se parezca a su original como el 10.º vecino real
(coseno 0.78 frente a 0.79), no como un clon; con ruido pequeño las consultas se
vuelven artificialmente fáciles y el HNSW parece visitar menos nodos al crecer.
Configuración de la app (M=8, ef_construction=50, k=102, ef_search=102), 200 consultas:

| Productos | Construcción | Recall@102 | HNSW | Nodos visitados | Exacta numpy | Exacta fila por fila |
|---:|---:|---:|---:|---:|---:|---:|
| 8,000 | 36 s | 0.940 | 6.2 ms | 608 (7.6 %) | **3.9 ms** | 20 ms |
| 25,000 | 121 s | 0.934 | **7.3 ms** | 789 (3.2 %) | 12.8 ms | 92 ms |
| 50,000 | 259 s | 0.919 | **8.8 ms** | 1,042 (2.1 %) | 24.3 ms | 110 ms |

- **El catálogo crece 6.25 veces; el HNSW visita 1.7 veces más nodos y tarda 1.4 veces
  más.** La búsqueda exacta vectorizada crece en proporción (6.2 veces).
- **Las curvas se cruzan entre 8k y 25k productos**: con la tienda actual (8k) la
  exacta en numpy todavía gana; desde ~15k gana el HNSW, aun escrito en Python puro
  frente a numpy (que corre en C). Frente a un recorrido fila por fila, como el del
  motor sin índice, el HNSW gana en todos los tamaños.
- El recall baja poco (0.94 → 0.92) y la construcción crece algo más que lineal
  (cada inserción busca en un grafo más grande).

## Latencia de la API con los datos reales

`GET /recomendaciones/{id}` con la tienda cargada en `data/app` (7,995 productos,
714 mil compras), ya con #118:

| Momento | Tiempo |
|---|---:|
| Arranque de la API (reconstruye los índices del motor) | ~6 min |
| Índice MobileNet, construido en segundo plano al arrancar | ~50 s más |
| Recomendación (mediana de 8 productos; mín.–máx.) | **229 ms** (150–624 ms) |
| Recomendación con `vector_imagen=sift` | 256 ms |

Antes de estas mejoras una recomendación tardaba ~4.7 s: la revisión de los 7,995
archivos de imagen en cada petición (3.5 s), el `SELECT` del catálogo para esa
revisión (0.6 s) y la categoría por recorrido de la tabla (0.6 s). Ahora los
archivos se revisan como mucho una vez por minuto y la categoría de cada candidato
se busca por clave primaria.

## Solo la métrica de tipo (exploración previa)

Con 505 consultas de prueba y pesos elegidos en validación, sin la señal de compras:

| Configuración | Pesos imagen / categoría | Tipo |
|---|---|---:|
| Texto solo | — | 70.6 % |
| Texto + SIFT (vocabulario de la tienda) + categoría *(solo técnicas del curso)* | 0.25 / 0.25 | 72.9 % |
| Texto + MobileNet + categoría | 0.25 / 1 | 74.7 % |
| Texto + CLIP ViT-B/32 + categoría | 0.25 / 1 | 75.4 % (n. s. frente a MobileNet) |
| Texto + CLIP entrenado con los tipos + categoría | 0.25 / 1 | 76.5 % (+1.7, con la etiqueta evaluada) |

Solo imagen: SIFT 35.4 %, histograma de color 22.9 %, MobileNet 57.7 %, CLIP 63.7 %.
De 30 errores revisados a mano, 19 eran la etiqueta mal sacada del título, 6
ambiguos, 3 complementarios y 2 errores claros: casi todo lo que falta es ruido de la
etiqueta.

## Límites

- La evaluación también descarta usuarios con más de 20 compras, igual que el filtro
  de la señal: puede favorecer un poco a la señal filtrada.
- 18 % de las consultas de tipo tiene un casi duplicado en el catálogo; sin ellas las
  cifras bajan cerca de un punto y el orden no cambia.
- En la app la imagen se busca con HNSW, no exacta; ver la sección de HNSW: no cambia el acierto.
