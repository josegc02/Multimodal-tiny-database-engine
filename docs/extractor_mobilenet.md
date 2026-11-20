# Extractor de imágenes del issue #102

MobileNetV2 preentrenado en ImageNet usa OpenCV DNN y ONNX. Se extrae la salida
de GlobalAveragePool_97, antes del clasificador, como vector de 1280 componentes
normalizado L2. Se redimensiona el lado menor a 256, se recorta el centro a
224 × 224 y se aplica la normalización RGB publicada por ONNX Model Zoo.

El modelo se instala desde la raíz del repositorio.

```sh
python -m engine.features.image.mobilenet
```

La descarga verifica SHA-256. El archivo ONNX queda local. Los pesos
proceden de [ONNX Model Zoo MobileNet](https://github.com/onnx/models/tree/main/validated/vision/classification/mobilenet),
bajo Apache-2.0. La inferencia usa los pesos existentes.

La API admite elegir representación en cada consulta.

```text
GET /recomendaciones/1                       # MobileNet, pesos 1,0.5,1, categoría 0.25 y RRF
GET /recomendaciones/1?vector_imagen=sift
```

MobileNet es el valor predeterminado; si falta el modelo y no se pidió una
representación, se recomienda con SIFT. SIFT utiliza la columna IMAGE e índice SQL
existentes. Por qué cambió el valor predeterminado: ver
[benchmarks/tienda](../benchmarks/tienda/README.md).
MobileNet usa el mismo HNSW del motor mediante un índice auxiliar sobre los IDs y
rutas de productos. Sus vectores se guardan en la subcarpeta mobilenet de la base.
El índice se construye en la primera consulta, que puede tardar varios minutos
con el catálogo completo. Para no esperar en la demo, precalcule los vectores
antes de levantar la API:

```bash
python -m tienda.indice_imagen --datos data/app
```

Las siguientes consultas reutilizan el grafo. Al reiniciar la API se reconstruye
desde los vectores guardados.

Se detectan cambios en IDs, rutas, tamaño y fecha de modificación de las imágenes.
Un cambio reconstruye el índice, reutilizando los vectores vigentes. El índice
tiene su propio lock y la extracción se hace **fuera del lock del motor**, así que
construirlo no congela el resto de la API (el asistente y la tienda siguen
respondiendo). Una imagen ilegible o ausente se omite y queda en
`ImageIndex.omitidos`; un producto sin vector recibe la señal de imagen vacía y se
recomienda con compras y texto. Solo si falta el modelo y se pidió `vector_imagen=mobilenet` se devuelve 503. Una
representación desconocida da 422. La selección permite alternar ambas
representaciones en la misma API.

La comparación reutiliza la métrica P@10 por categoría de la Parte 4 sobre COCO
1K, con coseno y los mismos parámetros HNSW. Excluye la propia imagen antes de
contar los diez vecinos. Los resultados y vecinos se guardan para inspección.

```sh
python -m benchmarks.comparar_extractores --dataset datasets/coco_subsets
```

Los resultados miden relevancia semántica en COCO. La calidad sobre productos de
la tienda requiere una evaluación específica de sus categorías.

## Resultado medido

Corrida del 19 de noviembre de 2026 con OpenCV 5.0.0: 1000 imágenes, las 73
consultas de `coco1k/queries.json` y HNSW con M=8, ef_construction=50,
ef_search=50 y semilla 0. Ambos extractores usan exactamente las mismas consultas
y parámetros. SIFT utiliza el vocabulario BoVW de 1024 palabras del repositorio.

| Extractor | Misma categoría entre los diez vecinos (P@10) |
| --- | ---: |
| SIFT + BoVW | 6,30 % |
| MobileNetV2 | 33,15 % |

La diferencia es de 26,85 puntos porcentuales. COCO admite varias etiquetas:
un vecino cuenta si contiene la categoría elegida para la consulta. La propia
imagen se excluye. Se pueden inspeccionar los [resultados agregados](../benchmarks/results/extractores/precision.json)
y los [vecinos de cada consulta](../benchmarks/results/extractores/queries.json).
