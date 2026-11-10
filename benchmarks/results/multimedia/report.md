# Comparación experimental multimedia (#59)

Los vectores son histogramas Bag of Visual Words (K=1024, TF-IDF) de los puntos SIFT de imágenes COCO. Tienen norma L2 igual a 1, así que ‖a − b‖² = 2 − 2·cos(a, b): la distancia euclidiana y el coseno ordenan los vecinos exactos igual. Las diferencias entre métricas vienen de cada índice: IVF agrupa con k-means euclidiano o esférico (coseno) y HNSW arma un grafo distinto según la métrica. Cada configuración usa el mismo corpus y las mismas consultas; el vector de la consulta se excluye de los resultados. Recall@10 compara los diez IDs recuperados con los diez vecinos exactos bajo la misma métrica. No mide relevancia semántica por categoría. Las imágenes sin puntos SIFT tienen el vector nulo: se excluyen de las corridas con coseno; casos por tamaño: 1000: 0, 10000: 0, 100000: 0.

| Imágenes | Métrica | Índice | Construcción (s) | Consulta media (ms) | Recall@10 | Pico RSS (MiB) | Memoria del índice (MiB) |
|---:|---|---|---:|---:|---:|---:|---:|
| 1000 | cosine | HNSW | 4.036 | 3.602 | 0.949 | 61.3 | 12.4 |
| 1000 | cosine | IVF | 0.079 | 2.387 | 0.704 | 75.1 | 28.0 |
| 1000 | euclidean | HNSW | 3.871 | 3.874 | 0.949 | 64.6 | 17.3 |
| 1000 | euclidean | IVF | 0.354 | 1.632 | 0.696 | 67.4 | 18.5 |
| 10000 | cosine | HNSW | 60.236 | 5.403 | 0.673 | 285.0 | 193.1 |
| 10000 | cosine | IVF | 1.860 | 15.822 | 0.686 | 337.3 | 244.8 |
| 10000 | euclidean | HNSW | 55.437 | 5.042 | 0.673 | 284.6 | 192.2 |
| 10000 | euclidean | IVF | 2.754 | 8.041 | 0.671 | 284.7 | 192.3 |
| 100000 | cosine | HNSW | 873.797 | 7.616 | 0.416 | 2575.0 | 2046.4 |
| 100000 | cosine | IVF | 115.308 | 77.383 | 0.688 | 2918.4 | 2390.1 |
| 100000 | euclidean | HNSW | 823.490 | 7.423 | 0.412 | 2575.5 | 2044.1 |
| 100000 | euclidean | IVF | 94.978 | 50.787 | 0.664 | 2576.1 | 2044.8 |

## Recomendaciones basadas en estas corridas

- 1000 imágenes, euclidean: **IVF** tuvo menor latencia media; **HNSW** obtuvo mayor Recall@10; **HNSW** usó menos memoria para el índice.
- 1000 imágenes, cosine: **IVF** tuvo menor latencia media; **HNSW** obtuvo mayor Recall@10; **HNSW** usó menos memoria para el índice.
- 10000 imágenes, euclidean: **HNSW** tuvo menor latencia media; **HNSW** obtuvo mayor Recall@10; **HNSW** usó menos memoria para el índice.
- 10000 imágenes, cosine: **HNSW** tuvo menor latencia media; **IVF** obtuvo mayor Recall@10; **HNSW** usó menos memoria para el índice.
- 100000 imágenes, euclidean: **HNSW** tuvo menor latencia media; **IVF** obtuvo mayor Recall@10; **HNSW** usó menos memoria para el índice.
- 100000 imágenes, cosine: **HNSW** tuvo menor latencia media; **IVF** obtuvo mayor Recall@10; **HNSW** usó menos memoria para el índice.

Estos resultados corresponden a una sola corrida por configuración, sin intervalos de confianza. El pico RSS incluye el intérprete, los vectores cargados y las páginas compartidas. La memoria del índice es el pico menos la memoria del proceso justo antes de construirlo (vectores ya cargados): aproxima lo que ocupa el índice y su construcción, igual para IVF y HNSW. Para comparar máquinas o tomar decisiones de producción hay que repetir las corridas bajo condiciones controladas.

![Construcción](construction.png)
![Consultas](query.png)
![Recall](recall.png)
![Memoria](memory.png)

[Galería de casos](gallery.html)
