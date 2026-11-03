-- Namespace propio: no modifica tablas de la parte espacial.
CREATE SCHEMA IF NOT EXISTS texto;
CREATE TABLE IF NOT EXISTS texto.dataset_loads (
    size integer PRIMARY KEY CHECK (size > 0),
    sha256 text NOT NULL,
    source_name text NOT NULL,
    language text NOT NULL CHECK (language = 'spanish'),
    loaded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
