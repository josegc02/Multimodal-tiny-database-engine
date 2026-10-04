# Datos espaciales (Parte 2, issue #25)

- **Puntos:** `generated/` contiene los puntos de 1K, 10K y 100K y los puntos de consulta.
  - Los genera `benchmarks/generate_spatial_datasets.py` de forma reproducible (semilla fija).
  - Esta carpeta no se versiona.
- **Polígonos:** `distritos_sinteticos_lima.geojson` sirve para pruebas y no representa límites administrativos reales.
  - GeoJSON usa el orden `[lon, lat]`; el motor usa `POINT(lat, lon)`.

| Archivo | Fuente | Licencia |
| :--- | :--- | :--- |
| `distritos_sinteticos_lima.geojson` | Generado por el equipo para pruebas | CC0 |

## Generación

```bash
python -m benchmarks.generate_spatial_datasets
python -m benchmarks.generate_spatial_datasets --sizes 1000 --queries 10 --output /tmp/spatial
```

Produce CSV común, CSV lon/lat para PostGIS, SQL de carga para el motor y los
100 centros de consulta reproducibles. Los comercios se concentran en cuatro
zonas de Lima con fondo uniforme para medir poda espacial.
