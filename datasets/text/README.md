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
