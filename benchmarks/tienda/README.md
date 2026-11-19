# Exactitud de las recomendaciones de la tienda

Mide qué tan parecidos son los 10 productos que recomienda `GET /recomendaciones/{id}`
sobre el catálogo real de la tienda: 7,995 productos de Amazon Reviews 2023
(Video_Games) con sus fotos.

## Métrica

**P@10 de tipo**: fracción de los 10 recomendados que son del mismo tipo de producto
que la consulta. Al azar acierta el **8.8 %**.

Las categorías de Amazon tienen demasiado ruido para servir de etiqueta: el mismo
mouse aparece como "Gaming Mice", "Accessories" o "PC" según el vendedor. El tipo se
saca del título con reglas (juego, mando, audífonos, cargador o cable, mouse, estuche,
teclado, soporte, mousepad, skin) y queda etiquetado el 83 % del catálogo.

## Protocolo

- **Validación**: 281 consultas (hasta 30 por tipo, semilla 42). Ahí se eligen la
  configuración y los pesos (imagen 0.25, 0.5, 0.75 o 1; categoría 0, 0.25, 0.5 o 1).
- **Prueba**: 505 consultas distintas (hasta 60 por tipo, semilla 2026). Con ellas se
  reportan los resultados, sin volver a elegir nada.
- Intervalos de confianza del 95 % por bootstrap pareado (5,000 remuestreos) sobre las
  mismas consultas.
- Texto: `MATCH(descripcion, ...) USING BM25` en nuestro motor (índice SPIMI en
  inglés). Imagen: búsqueda exacta por coseno, para comparar los extractores sin el
  error del HNSW. Fusión: cada señal dividida por su máximo, como `fusionar`.
- **Sin la señal de compras**: aún no se mide (ver Límites).

## Resultados (505 consultas de prueba)

| Configuración | Pesos imagen / categoría | P@10 | IC 95 % |
|---|---|---:|---|
| Antes: texto + SIFT, pesos iguales | 1 / 0 | 49.9 % | 46.9–52.7 |
| Texto solo | — | 70.6 % | 67.8–73.3 |
| Texto + categoría | 0 / 0.25 | 72.2 % | 69.4–75.0 |
| Texto + SIFT (vocabulario de la tienda) + categoría | 0.25 / 0.25 | 72.9 % | 70.0–75.7 |
| Texto + MobileNet | 0.25 / 0 | 71.8 % | 69.0–74.5 |
| **Texto + MobileNet + categoría (nuevo valor predeterminado)** | **0.25 / 0.25** | **74.2 %** | — |
| Texto + MobileNet + categoría | 0.25 / 1 | 74.7 % | 72.0–77.5 |
| Texto + CLIP ViT-B/32 + categoría | 0.25 / 1 | 75.4 % | 72.6–78.1 |
| Texto + CLIP entrenado con los tipos + categoría | 0.25 / 1 | 76.5 % | 73.7–79.1 |

- **El cambio grande es bajar el peso de SIFT**: +25 puntos frente a antes (IC de la
  diferencia: +22 a +27). Normalizado por su máximo, SIFT da similitudes casi iguales
  para todo y empujaba productos de otro tipo con la misma fuerza que el texto.
- El peso de la categoría casi no importa (0.25: 74.2 %, 0.5: 74.5 %, 1: 74.7 %). Se
  eligió 0.25 porque con 1 actúa casi como un filtro y apagaría los productos
  complementarios que trae la señal de compras.
- CLIP no gana a MobileNet de forma significativa (+0.7, IC −0.1 a +1.4) y pesa 350 MB.
  Entrenado con los tipos gana +1.7 (IC +0.9 a +2.6), pero con la misma etiqueta con la
  que se evalúa.
- Solo con técnicas del curso (SIFT con vocabulario de la tienda + categoría) se llega
  a 72.9 %; MobileNet (con categoría 1) suma +1.9 sobre eso (IC +0.9 a +2.8).
- Solo imagen (validación): SIFT 35.4 %, histograma de color 22.9 %, MobileNet 57.7 %,
  CLIP 63.7 %.

## Análisis de errores

De 30 recomendaciones contadas como "otro tipo", elegidas al azar: 19 eran la etiqueta
mal sacada del título (una funda de Switch etiquetada "mando" porque el título dice
"controller"), 6 eran ambiguas o accesorios afines, 3 complementarias (base para
volante → volante) y 2 errores claros del sistema. La mayor parte de lo que falta para
el 100 % es ruido de la etiqueta, no de la app.

## Límites

- La métrica favorece al texto: el tipo sale del título y el texto del mismo producto.
- No mide la señal de compras, que trae sobre todo complementarios (contados aquí como
  error). Se medirá con una segunda métrica de comportamiento: recuperar los productos
  co-reseñados por usuarios apartados.
- 18 % de las consultas de prueba tiene un casi duplicado en el catálogo (mismo inicio
  de título); sin ellas las cifras bajan cerca de un punto y el orden no cambia.
