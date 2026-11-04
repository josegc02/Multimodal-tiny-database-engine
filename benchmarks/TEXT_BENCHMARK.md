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
VmRSS inicial en Linux. En Windows se usan PeakWorkingSetSize y WorkingSetSize
de GetProcessMemoryInfo, respectivamente. Ambos se reportan en bytes.
Para PostgreSQL se mide el backend Linux del servidor dentro del
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

## Ejecutar y auditar

```sh
.venv/bin/python -m pip install -r requirements.txt -r requirements-text-postgres.txt
docker compose -f postgres_text/docker-compose.yml up -d --wait
# Generar solo si aún no existe datasets/text/generated:
.venv/bin/python -m benchmarks.generate_text_datasets
.venv/bin/python -m benchmarks.bench_text
.venv/bin/python -m benchmarks.validate_text_results benchmarks/results/text
.venv/bin/python -m benchmarks.plot_text benchmarks/results/text
.venv/bin/python -m benchmarks.text_report benchmarks/results/text
```

El directorio de salida debe ser nuevo; no se sobrescriben resultados.
Para otra corrida, usar `--output benchmarks/results/smoke/otra-corrida`.
Una prueba rápida admite `--sizes 1000 --repetitions 1`. `--sin-postgres`
marca explícitamente la corrida como parcial; no es la comparación oficial.
El Docker debe ser local y contener el backend del DSN: `--container` indica
el nombre y `--dsn` la conexión. Para PostgreSQL remoto, esta medición de
memoria no es aplicable y la corrida falla en lugar de reportar memoria del
cliente como si fuera la del servidor.

No ejecutar otras cargas intensivas simultáneamente si se desea reducir la
variación del equipo. Las corridas publicadas corresponden a una estación
de trabajo, no a un servidor dedicado ni a una medición de caché fría.

## Archivos

| Archivo | Contenido |
|---|---|
| `metadata.json` | Código, entorno, hashes, parámetros, marca de completitud |
| `build_runs.csv` | Carga/construcción, disco y memoria por corrida |
| `query_runs.csv` | Una fila por consulta, repetición y técnica |
| `rankings.csv` | IDs, posiciones, scores y relevancia de cada respuesta |
| `build_summary.csv` | Medias, desviación, mínimo y máximo entre repeticiones |
| `query_group_runs.csv` | Promedios por longitud dentro de cada repetición |
| `query_summary.csv` | Resumen entre repeticiones de esos promedios |
| `plans.json` | Plan natural de PostgreSQL por consulta, fuera del cronómetro |
| `tables.md`, PNG | Tablas y gráficas regenerables sin repetir mediciones |

Las gráficas muestran media y rango mínimo–máximo; las desviaciones estándar
también están en CSV. Los tres grupos tienen 6, 12 y 12 consultas; las medias
de cada grupo pesan igual cada consulta, sin confundir consultas diferentes
con repeticiones de una misma medición.

## Límites de interpretación

- PostgreSQL usa una tabla temporal con el mismo contenido, vector generado
  y clave primaria de #50. No hay WAL de datos temporales; no se mide
  durabilidad transaccional. El motor tampoco ejecuta una transacción SQL
  con WAL: se usan sus archivos directamente. La creación de la PK de
  PostgreSQL está incluida en carga y su tamaño en el total.
- La memoria Python incluye intérprete, qrels, cachés de stemming y buffers,
  además del índice. El RSS inicial se toma después de cargar los qrels.
  El backend PostgreSQL incluye mappings compartidos y buffers locales;
  `client_peak_bytes` conserva por separado el pico del cliente Python.
  Un número menor de RSS no demuestra por sí solo un índice más compacto.
- SPIMI lee documentos para construir pesos y normas durante construcción;
  GIN recibe un vector ya calculado durante carga. Comparar únicamente
  CREATE INDEX con SPIMI exageraría la diferencia de preparación completa.
- Ambas técnicas del motor comparten el mismo SPIMI. Diferencias pequeñas
  en su construcción reflejan variación entre corridas, no una ventaja de
  TF-IDF sobre BM25 al indexar.
- Las consultas usan candidatos OR, pero los diccionarios y los rankings
  son distintos. Solo se comparan métricas de calidad por ID, nunca scores.
- PostgreSQL elige el plan natural (puede ser Seq Scan). GIN etiqueta la
  configuración con el índice disponible, no una promesa de usarlo siempre.
  Los planes se conservan para comprobarlo. Se desactiva paralelismo de
  consulta para limitar la memoria medida a un backend; tablas temporales
  ya limitan las opciones de paralelismo.
- No se miden memoria exclusiva del índice, caché fría, concurrencia,
  temporales máximos en disco, WAL ni p95 de producción. Tres repeticiones
  permiten una comparación descriptiva, no significancia estadística.

El diseño sigue el Laboratorio 09 (tamaños, repeticiones, curvas y análisis
con datos concretos) y el Laboratorio 10/PPT 09 (GIN, ranking y planes).
Los tres tamaños se toman del checklist #51; el laboratorio general pide
cinco tamaños, pero este entregable usa los 1K/10K/100K especificados.

## Validación y checklist #51

La corrida publicada completó 27 construcciones, 810 consultas medidas y
8.100 resultados top-10. El auditor recalculó relevancia, comprobó cobertura
y contrastó los hashes con el corpus. La suite completa pasó con 552 pruebas
y una omitida, incluyendo integración con PostgreSQL y el worker de memoria.
Persisten avisos de archivos sin cerrar en pruebas anteriores del proyecto.

Los mensajes de los commits locales de #51 se tradujeron al español a pedido
del usuario. La revisión equivalente de código quedó en `git_revision` y
el hash previo en `git_revision_before_message_translation`; los árboles
de archivos son idénticos. Esto preserva la procedencia de las mediciones.

- [x] Benchmark TF-IDF/coseno, BM25 y PostgreSQL GIN.
- [x] Datasets 1K, 10K y 100K.
- [x] Consultas de 1, 3 y 5+ palabras.
- [x] Tiempo de construcción y preparación completa.
- [x] Tiempo de consulta.
- [x] Precision@10 y Recall@10.
- [x] Memoria y espacio en disco, con alcance documentado.
- [x] Seis gráficas comparativas regenerables.
- [x] Tabla de ventajas y desventajas en el informe.
- [x] Conclusiones sustentadas en las corridas, sección 9 del informe.
