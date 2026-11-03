# Protocolo experimental de texto (#51)

Se comparan TF-IDF/coseno lnc.ltc, BM25 (k1=1.2, b=0.75) y PostgreSQL
GIN + ts_rank (normalización 0). Mismos CSV, IDs, consultas OR y qrels de
#49; se evalúan 1K, 10K y 100K, tres repeticiones y top-10. Las 30 consultas
se agrupan por 1, 3 y 6 palabras. El orden se mezcla con una semilla fija.

Cada técnica/repetición usa un proceso Python nuevo; PostgreSQL utiliza
una conexión nueva y una tabla temporal que desaparece al cerrarla. No se
reemplazan las tablas de #50. TF-IDF y BM25 construyen el mismo SPIMI en
corridas independientes: sus tiempos de construcción no son dos algoritmos.

Carga, construcción y consultas tienen cronómetros separados. SPIMI incluye
análisis de texto al construir; PostgreSQL genera tsvector durante COPY,
por lo que se publican también carga y carga+construcción. La carga Python
incluye la lectura CSV e inserción HeapFile/TextStore. ANALYZE queda fuera.

Una pasada de calentamiento precede las consultas medidas; no se vacía la
caché del sistema operativo. El tiempo de consulta incluye devolver IDs y
scores al llamador (incluida la comunicación local con PostgreSQL). Las
métricas de relevancia y EXPLAIN se calculan fuera del cronómetro.

Memoria: VmHWM del proceso nuevo durante carga+construcción+workload, y
VmRSS inicial. Para PostgreSQL se mide el backend del servidor dentro del
contenedor, además del cliente Python. RSS incluye páginas compartidas y
no representa memoria exclusiva del índice ni todo el servidor. No se
restan picos ni se presentan esos valores como asignaciones netas.

Disco: índice de búsqueda separado del total de la relación. PostgreSQL
incluye heap, TOAST, vector almacenado y GIN; Python incluye heap, TEXT y
SPIMI. No se incluye WAL, temporales de construcción ni el CSV de entrada.

Precision@10 divide por 10 aunque haya menos respuestas. Recall@10 divide
por relevantes del mismo tamaño; sin relevantes se reporta NA. Los IDs
duplicados son un error, no aciertos adicionales. Los qrels son sintéticos
y no permiten afirmar superioridad sobre noticias reales.
