-- Parte 4: busqueda multimedia con las 18 imagenes de ./fotos.
-- Ejecutar este bloque de carga UNA VEZ por sesion del frontend.
-- En el editor, seleccionar con el mouse el bloque o consulta y pulsar Ejecutar.
-- Las seis columnas apuntan al mismo archivo: MediaStore reutiliza su vector.
-- Se necesita abrir el frontend desde la raiz del proyecto para ver la galeria.

CREATE TABLE imagenes_demo (
    id INT PRIMARY KEY,
    nombre VARCHAR(30),
    hnsw_euclidean IMAGE,
    hnsw_cosine IMAGE,
    hnsw_dot IMAGE,
    ivf_euclidean IMAGE,
    ivf_cosine IMAGE,
    ivf_dot IMAGE
);

INSERT INTO imagenes_demo VALUES
    (1, 'Beagle 1', 'fotos/beagle1.png', 'fotos/beagle1.png', 'fotos/beagle1.png', 'fotos/beagle1.png', 'fotos/beagle1.png', 'fotos/beagle1.png'),
    (2, 'Beagle 2', 'fotos/beagle2.png', 'fotos/beagle2.png', 'fotos/beagle2.png', 'fotos/beagle2.png', 'fotos/beagle2.png', 'fotos/beagle2.png'),
    (3, 'Beagle 3', 'fotos/beagle3.png', 'fotos/beagle3.png', 'fotos/beagle3.png', 'fotos/beagle3.png', 'fotos/beagle3.png', 'fotos/beagle3.png'),
    (4, 'Beagle 4', 'fotos/beagle4.png', 'fotos/beagle4.png', 'fotos/beagle4.png', 'fotos/beagle4.png', 'fotos/beagle4.png', 'fotos/beagle4.png'),
    (5, 'Beagle 5', 'fotos/beagle5.png', 'fotos/beagle5.png', 'fotos/beagle5.png', 'fotos/beagle5.png', 'fotos/beagle5.png', 'fotos/beagle5.png'),
    (6, 'Gato 1', 'fotos/gato1.png', 'fotos/gato1.png', 'fotos/gato1.png', 'fotos/gato1.png', 'fotos/gato1.png', 'fotos/gato1.png'),
    (7, 'Gato 2', 'fotos/gato2.png', 'fotos/gato2.png', 'fotos/gato2.png', 'fotos/gato2.png', 'fotos/gato2.png', 'fotos/gato2.png'),
    (8, 'Gato 3', 'fotos/gato3.png', 'fotos/gato3.png', 'fotos/gato3.png', 'fotos/gato3.png', 'fotos/gato3.png', 'fotos/gato3.png'),
    (9, 'Gato 4', 'fotos/gato4.png', 'fotos/gato4.png', 'fotos/gato4.png', 'fotos/gato4.png', 'fotos/gato4.png', 'fotos/gato4.png'),
    (10, 'Gato 5', 'fotos/gato5.png', 'fotos/gato5.png', 'fotos/gato5.png', 'fotos/gato5.png', 'fotos/gato5.png', 'fotos/gato5.png'),
    (11, 'Libro 1', 'fotos/libro1.png', 'fotos/libro1.png', 'fotos/libro1.png', 'fotos/libro1.png', 'fotos/libro1.png', 'fotos/libro1.png'),
    (12, 'Libro 2', 'fotos/libro2.png', 'fotos/libro2.png', 'fotos/libro2.png', 'fotos/libro2.png', 'fotos/libro2.png', 'fotos/libro2.png'),
    (13, 'Libro 3', 'fotos/libro3.png', 'fotos/libro3.png', 'fotos/libro3.png', 'fotos/libro3.png', 'fotos/libro3.png', 'fotos/libro3.png'),
    (14, 'Personas 1', 'fotos/personas1.png', 'fotos/personas1.png', 'fotos/personas1.png', 'fotos/personas1.png', 'fotos/personas1.png', 'fotos/personas1.png'),
    (15, 'Personas 2', 'fotos/personas2.png', 'fotos/personas2.png', 'fotos/personas2.png', 'fotos/personas2.png', 'fotos/personas2.png', 'fotos/personas2.png'),
    (16, 'Personas 3', 'fotos/personas3.png', 'fotos/personas3.png', 'fotos/personas3.png', 'fotos/personas3.png', 'fotos/personas3.png', 'fotos/personas3.png'),
    (17, 'Uni 1', 'fotos/uni1.png', 'fotos/uni1.png', 'fotos/uni1.png', 'fotos/uni1.png', 'fotos/uni1.png', 'fotos/uni1.png'),
    (18, 'Uni 2', 'fotos/uni2.png', 'fotos/uni2.png', 'fotos/uni2.png', 'fotos/uni2.png', 'fotos/uni2.png', 'fotos/uni2.png');

CREATE INDEX demo_hnsw_euclidean ON imagenes_demo (hnsw_euclidean) USING HNSW WITH (METRIC = euclidean);
CREATE INDEX demo_hnsw_cosine ON imagenes_demo (hnsw_cosine) USING HNSW WITH (METRIC = cosine);
CREATE INDEX demo_hnsw_dot ON imagenes_demo (hnsw_dot) USING HNSW WITH (METRIC = dot);
CREATE INDEX demo_ivf_euclidean ON imagenes_demo (ivf_euclidean) USING IVF WITH (METRIC = euclidean);
CREATE INDEX demo_ivf_cosine ON imagenes_demo (ivf_cosine) USING IVF WITH (METRIC = cosine);
CREATE INDEX demo_ivf_dot ON imagenes_demo (ivf_dot) USING IVF WITH (METRIC = dot);

-- Ejecutar las consultas de abajo DE UNA EN UNA para ver cada galeria.
-- Las seis primeras usan beagle1.png y muestran sus 10 vecinos mas cercanos.
-- La foto consultada tambien esta en la tabla, asi que normalmente sale primera.
-- SIMILARITY_SCORE crece con la similitud. Para euclidean es 1/(1+distancia).
-- Los vectores BoVW estan normalizados: cosine, dot y euclidean pueden dar
-- el mismo orden, aunque sus puntajes tienen distinta interpretacion.
-- Con 18 imagenes IVF ya entrena centroides (desde 16); el indice es aproximado.

-- 1. HNSW + distancia euclidiana.
SELECT nombre, hnsw_euclidean, SIMILARITY_SCORE() AS score
FROM imagenes_demo
WHERE SIMILAR_TO(hnsw_euclidean, 'fotos/beagle1.png', k=10) USING HNSW WITH METRIC=euclidean
ORDER BY score DESC;

-- 2. HNSW + similitud coseno.
SELECT nombre, hnsw_cosine, SIMILARITY_SCORE() AS score
FROM imagenes_demo
WHERE SIMILAR_TO(hnsw_cosine, 'fotos/beagle1.png', k=10) USING HNSW WITH METRIC=cosine
ORDER BY score DESC;

-- 3. HNSW + producto punto.
SELECT nombre, hnsw_dot, SIMILARITY_SCORE() AS score
FROM imagenes_demo
WHERE SIMILAR_TO(hnsw_dot, 'fotos/beagle1.png', k=10) USING HNSW WITH METRIC=dot
ORDER BY score DESC;

-- 4. IVF + distancia euclidiana.
SELECT nombre, ivf_euclidean, SIMILARITY_SCORE() AS score
FROM imagenes_demo
WHERE SIMILAR_TO(ivf_euclidean, 'fotos/beagle1.png', k=10) USING IVF WITH METRIC=euclidean
ORDER BY score DESC;

-- 5. IVF + similitud coseno.
SELECT nombre, ivf_cosine, SIMILARITY_SCORE() AS score
FROM imagenes_demo
WHERE SIMILAR_TO(ivf_cosine, 'fotos/beagle1.png', k=10) USING IVF WITH METRIC=cosine
ORDER BY score DESC;

-- 6. IVF + producto punto.
SELECT nombre, ivf_dot, SIMILARITY_SCORE() AS score
FROM imagenes_demo
WHERE SIMILAR_TO(ivf_dot, 'fotos/beagle1.png', k=10) USING IVF WITH METRIC=dot
ORDER BY score DESC;

-- 7. Otra consulta: buscar a partir de gato1.png con HNSW + coseno.
SELECT nombre, hnsw_cosine, SIMILARITY_SCORE() AS score
FROM imagenes_demo
WHERE SIMILAR_TO(hnsw_cosine, 'fotos/gato1.png', k=10) USING HNSW WITH METRIC=cosine
ORDER BY score DESC;

-- 8. Buscar a partir de libro1.png.
SELECT nombre, hnsw_cosine, SIMILARITY_SCORE() AS score
FROM imagenes_demo
WHERE SIMILAR_TO(hnsw_cosine, 'fotos/libro1.png', k=10) USING HNSW WITH METRIC=cosine
ORDER BY score DESC;

-- 9. Buscar a partir de personas1.png.
SELECT nombre, hnsw_cosine, SIMILARITY_SCORE() AS score
FROM imagenes_demo
WHERE SIMILAR_TO(hnsw_cosine, 'fotos/personas1.png', k=10) USING HNSW WITH METRIC=cosine
ORDER BY score DESC;

-- 10. Buscar a partir de uni1.png.
SELECT nombre, hnsw_cosine, SIMILARITY_SCORE() AS score
FROM imagenes_demo
WHERE SIMILAR_TO(hnsw_cosine, 'fotos/uni1.png', k=10) USING HNSW WITH METRIC=cosine
ORDER BY score DESC;
