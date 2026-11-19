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

| Configuración | Tipo | Comportamiento |
|---|---:|---:|
| Antes: texto + SIFT, pesos 1,1,1, compras de antes | 47.1 % [44.3, 49.9] | 6.2 % [5.3, 7.2] |
| #117 inicial: MobileNet 0.25 + categoría 0.25 | 64.7 % [61.9, 67.6] | 8.9 % [7.7, 10.1] |
| **Elegida: RRF, 101 candidatos, compras filtradas, pesos 1/0.5/1, categoría 0.25** | **70.9 %** [68.1, 73.5] | **10.2 %** [8.9, 11.5] |
| Elegida − #117 inicial | +6.1 [+4.6, +7.7] | +1.3 [+0.5, +2.2] |

La elegida gana en las dos métricas. Compras filtradas: solo usuarios con 2 a 20
compras y solo pares a 30 días o menos.

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
compraron" es un self-JOIN en nuestro motor. Hubo que corregir el optimizador:

| Versión del motor | Plan | Mediana | Máximo (producto más comprado) |
|---|---|---:|---:|
| Antes | Hash join de toda la tabla consigo misma, filtro al final | 27.7 s | 39 s |
| **Pushdown de selección + valores distintos con KMV** | Index scan en `a.producto_id`, *index nested loop* en `usuario` | **18 ms** | **632 ms** |

El JOIN del motor devuelve los mismos pares que el cálculo en Python en 20 de 20
productos. Ver `docs/sql_parser.md`.

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
- En la app la imagen se busca con HNSW, no exacta.
