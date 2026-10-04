-- Esquema de PostGIS para la comparación con GiST (issue #26).
-- Ojo: PostGIS ordena las coordenadas como (lon, lat); nuestro motor usa POINT(lat, lon).

CREATE EXTENSION IF NOT EXISTS postgis;

-- geography: distancias en metros sobre el esferoide (comparable con Haversine).
CREATE TABLE IF NOT EXISTS puntos (
    id        INTEGER PRIMARY KEY,
    nombre    VARCHAR(30) NOT NULL,
    categoria VARCHAR(15) NOT NULL,
    ubicacion GEOGRAPHY(POINT, 4326) NOT NULL
);

-- El índice GiST se crea después de cargar los datos para medir su construcción:
--   CREATE INDEX puntos_ubicacion_gist ON puntos USING GIST (ubicacion);

CREATE TABLE IF NOT EXISTS distritos (
    id     INTEGER PRIMARY KEY,
    nombre VARCHAR(60) NOT NULL,
    geom   GEOMETRY(MULTIPOLYGON, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS distritos_geom_gist ON distritos USING GIST (geom);

-- Consultas equivalentes a las de nuestro motor:
--
-- Rango (radio en metros):
--   SELECT id FROM puntos
--   WHERE ST_DWithin(ubicacion, ST_MakePoint(-77.0428, -12.0464)::geography, 5000);
--
-- k-NN (operador <-> usa el índice GiST):
--   SELECT id FROM puntos
--   ORDER BY ubicacion <-> ST_MakePoint(-77.0428, -12.0464)::geography
--   LIMIT 10;
--
-- Intersección con un polígono (distrito):
--   SELECT p.id FROM puntos p JOIN distritos d ON ST_Within(p.ubicacion::geometry, d.geom)
--   WHERE d.nombre = 'Miraflores';
