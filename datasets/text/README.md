# Noticias sintéticas en español — issue #49

Colección controlada, escrita para este proyecto, inspirada en `news_es.csv`
del Laboratorio 09 (Bag of Words, Coseno e Índice Invertido). El CSV original
no se distribuye con los materiales de clase disponibles. No son noticias
reales ni juicios humanos: permiten validar recuperación y escalabilidad,
pero no demostrar calidad en un corpus periodístico real.

La unidad es un documento UTF-8 con `id,url,contenido,categoria,tema`.
`contenido` es el único campo indexado; categoría y tema son etiquetas de
evaluación, nunca entradas al ranking. Los identificadores son estables y
los conjuntos de 1K y 10K serán prefijos del de 100K con la misma semilla.

El diseño conserva el pipeline de clase: texto → preprocesamiento español
→ bag of words → índice invertido → ranking. Reutiliza el preprocesador y
SPIMI del motor; no introduce otra implementación de TF-IDF o BM25.

Los juicios se derivan del tema editorial asignado antes de redactar cada
documento, no de sus palabras ni del resultado de ningún algoritmo. Esto
es relevancia temática sintética; debe identificarse así en el informe.

## Generación y verificación

Desde la raíz del repositorio, con las dependencias de `requirements.txt`:

```sh
.venv/bin/python -m benchmarks.generate_text_datasets
.venv/bin/python -m benchmarks.text_validation datasets/text/generated
```

La semilla predeterminada es 42. Se generan `noticias_1000.csv`,
`noticias_10000.csv`, `noticias_100000.csv`, `queries.csv`, un `qrels_<N>.csv`
y un `cargar_motor_<N>.sql` por tamaño. `metadata.json` identifica versión,
semilla, idioma, cardinalidades y hashes SHA-256 de CSV. Los SQL contienen
rutas absolutas y se regeneran al mover los datos; no forman parte del hash
reproducible del corpus. El directorio de salida debe ser nuevo.

Para una prueba pequeña o una segunda semilla:

```sh
.venv/bin/python -m benchmarks.generate_text_datasets --sizes 120 240 --seed 7 --output /tmp/noticias-prueba
```

Hay seis categorías y doce temas; la asignación cíclica mantiene cobertura
en los tres tamaños oficiales. Los textos tienen frecuencias y longitudes
variables, saltos de línea, tildes y menciones de temas secundarios; algunos
superan 4 KB y ejercitan el almacenamiento TEXT. Los IDs y URLs son únicos,
pero el vocabulario y las frases son deliberadamente reutilizados: no es un
corpus lingüísticamente tan diverso como noticias reales. `example.invalid`
identifica URLs ficticias; no se descargan páginas.

## Consultas y relevancia

`queries.csv` contiene 30 intenciones: 6 consultas de una palabra, 12 de tres
y 12 de seis. Todas conservan esa cantidad de tokens después del
preprocesamiento español del motor. Los términos de contexto de las consultas
largas pueden no aparecer en los documentos: no se garantiza que cada palabra
aporte candidatos. `category`, `topic` e `intent` permiten auditar los juicios.

En `qrels_<N>.csv`, cada fila positiva tiene `query_id,doc_id,relevance=1`.
Se juzgan todos los pares consulta/documento: los pares omitidos valen cero.
La consulta de una palabra acepta la categoría editorial; las específicas
exigen el tema principal. Una mención secundaria no vuelve relevante al texto.
Los qrels de cada tamaño solo contienen IDs de ese subconjunto.

Para #51, usando IDs del CSV (no RIDs físicos):

- Precision@10 = relevantes distintos recuperados en los primeros 10 / 10.
- Recall@10 = relevantes distintos recuperados en los primeros 10 / total
  de relevantes de esa consulta en **ese tamaño**.
- Si se recuperan menos de 10 documentos, el denominador de precisión sigue
  siendo 10; si no hay relevantes, reportar recall como no aplicable.

El verificador muestra el total relevante por consulta. Por ejemplo, en 1K
hay 168 noticias relevantes para economía y 84 para inflación. El recall
máximo con diez respuestas es respectivamente 10/168 y 10/84. Al crecer el
corpus, Recall@10 puede disminuir incluso con diez aciertos; no confundir
ese efecto del denominador con una degradación del ranking.
