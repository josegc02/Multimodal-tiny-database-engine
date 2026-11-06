# Comparación experimental multimedia (#59)

**Vectores.** Por defecto (`--features bovw`) cada imagen se representa con
ExtractFeatures del enunciado: sus puntos SIFT se cuantizan con el vocabulario
Bag of Visual Words de `models/bow_image_k256.npz` y el histograma se pesa con
TF-IDF (256 dimensiones). Una imagen sin puntos SIFT queda en el vector nulo y
se excluye de las corridas con coseno. `--features sift-mean` reproduce los
resultados publicados en #83, que usaban el promedio SIFT (128 dimensiones);
el resto de esta página describe esa versión.

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
la llamada al índice. El pico RSS sí incluye el proceso Python y el índice.

La referencia de Recall@10 son los diez vecinos exactos del mismo conjunto de
vectores, excluida la consulta. Esta medida evalúa la aproximación del índice;
no demuestra relevancia semántica. IVF usa `nlist ≈ √N` y `nprobe ≈ √nlist`;
HNSW usa `M=8`, `ef_construction=50` y `ef_search=50`, con semilla 42.
Esos parámetros están fijos para ambas métricas y no se ajustaron por dataset.

La salida contiene `summary.csv`, `queries.json`, cuatro gráficas PNG,
`gallery.html` y `report.md`. El informe construye sus recomendaciones a
partir de los números medidos. Ningún resultado de 1K/10K/100K se incluye en
el repositorio sin haber ejecutado los experimentos sobre el COCO completo.
La implementación HNSW es Python puro: la corrida de 100K puede durar mucho
tiempo y requerir bastante memoria.
