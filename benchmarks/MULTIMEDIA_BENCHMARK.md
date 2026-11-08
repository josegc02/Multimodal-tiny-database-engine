# Comparación experimental multimedia (#59)

**Vectores.** Por defecto (`--features bovw`) cada imagen se representa con
ExtractFeatures del enunciado: sus puntos SIFT se cuantizan con el vocabulario
Bag of Visual Words de `models/bow_image_k1024.npz` y el histograma se pesa con
TF-IDF (1024 dimensiones). Las cachés de vectores de un
vocabulario anterior (K = 256) se vuelven a extraer. Una imagen sin puntos SIFT queda en el vector nulo y
se excluye de las corridas con coseno. Los resultados publicados en
`benchmarks/results/multimedia/` se midieron así. `--features sift-mean`
reproduce la versión anterior (#83), que usaba el promedio SIFT (128 dimensiones)
y, para imágenes sin puntos SIFT, el histograma gris descrito abajo.

El script usa los subconjuntos de imágenes COCO de #58 y el promedio de
descriptores SIFT de #52. La comparación cubre IVF y HNSW, distancia euclidiana
y coseno, y los tamaños 1K, 10K y 100K. Las consultas vienen de `queries.json`
de #58; se excluye la propia imagen consultada y se buscan diez vecinos.
Si una imagen no tiene puntos SIFT, se usa su histograma de intensidad gris
de 128 dimensiones, escalado a la norma mediana de los vectores SIFT. La salida
`fallback_counts.json` registra cuántas imágenes necesitaron esta alternativa.

```sh
python -m pip install -r requirements.txt
python scripts/download_coco.py
python scripts/create_subsets.py
python scripts/generate_queries.py
python -m benchmarks.multimedia_compare --output benchmarks/results/smoke/multimedia
```

Se puede probar solo 1K con `--sizes 1000`. Los archivos de COCO son grandes;
el script falla si faltan imágenes o consultas. Cada combinación de índice y
métrica corre en un proceso nuevo. Los vectores SIFT se extraen una vez por
tamaño y se comparten mediante un archivo `.npz` dentro del directorio de
salida. El tiempo de construcción excluye la extracción SIFT, la lectura del
cache y la preparación de consultas. El tiempo medio de consulta incluye solo
la llamada al índice. El pico RSS sí incluye el proceso Python, los vectores
cargados y el índice. Ambos índices guardan una copia float64 de cada vector
(100K × 1024 × 8 B ≈ 800 MB), así que esa copia domina la memoria; el grafo de HNSW
y las listas de IVF agregan poco. La columna *Memoria del índice* (y `memory.png`) es el
pico menos la memoria del proceso justo antes de construir el índice, cuando los
vectores ya están cargados: aísla lo que ocupan el índice y su construcción.

Con vectores BoVW (norma 1) la distancia euclidiana y el coseno ordenan igual a
los vecinos exactos, porque ‖a − b‖² = 2 − 2·cos(a, b); las diferencias entre
métricas salen de cada índice (k-means euclidiano o esférico en IVF, grafo
distinto en HNSW). El vocabulario se entrenó con 500 fotos de `coco1k`: no
afecta Recall@10 ni tiempos, pero puede favorecer un poco la precisión
semántica de la galería en el tamaño de 1K.

La referencia de Recall@10 son los diez vecinos exactos del mismo conjunto de
vectores, excluida la consulta. Esta medida evalúa la aproximación del índice;
no demuestra relevancia semántica. IVF usa `nlist ≈ √N` y `nprobe ≈ √nlist`;
HNSW usa `M=8` (2·M vecinos en la capa 0), `ef_construction=50` y `ef_search=50`, con semilla 42,
y la heurística de selección de vecinos del algoritmo original. Esos parámetros están fijos para ambas métricas y no se ajustaron por dataset.

La salida contiene `summary.csv`, `queries.json`, cuatro gráficas PNG,
`gallery.html` y `report.md`. El informe construye sus recomendaciones a
partir de los números medidos. Ningún resultado de 1K/10K/100K se incluye en
el repositorio sin haber ejecutado los experimentos sobre el COCO completo.
La implementación HNSW es Python puro: la corrida de 100K puede durar mucho
tiempo y requerir bastante memoria.
