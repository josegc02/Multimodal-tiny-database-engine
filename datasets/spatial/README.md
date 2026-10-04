# Datos espaciales (Parte 2, issue #25)

- **Puntos:** `generated/` contiene los puntos de 1K, 10K y 100K y los puntos de consulta.
  - Los genera `benchmarks/generate_spatial_datasets.py` de forma reproducible (semilla fija).
  - Esta carpeta no se versiona.
- **Polígonos:** los de distritos (por ejemplo, los de Lima) se guardan aquí como GeoJSON, indicando la fuente y la licencia.
  - GeoJSON usa el orden `[lon, lat]`; el motor usa `POINT(lat, lon)`.

| Archivo | Fuente | Licencia |
| :--- | :--- | :--- |
| _pendiente_ | | |
