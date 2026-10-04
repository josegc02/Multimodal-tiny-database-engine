"""Datasets reproducibles de comercios sintéticos en Lima (issue #25).

    python -m benchmarks.generate_spatial_datasets
    python -m benchmarks.generate_spatial_datasets --sizes 1000 --queries 10 --output /tmp/spatial

Por cada tamaño escribe en datasets/spatial/generated/:
- puntos_<N>.csv          id, nombre, categoria, lat, lon
- postgis_puntos_<N>.csv  el mismo contenido en orden lon, lat (PostGIS)
- cargar_motor_<N>.sql    CREATE TABLE, INSERT por lotes y CREATE INDEX ... USING RTREE
y además consultas.csv (centros de consulta) y metadata.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.spatial.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "datasets" / "spatial" / "generated"
LIMA_BOUNDS = {"min_lat": -12.30, "max_lat": -11.75, "min_lon": -77.20, "max_lon": -76.80}
CATEGORIAS = ("tienda", "restaurante", "gasolinera", "farmacia", "banco")
SCHEMA = [("id", "int"), ("nombre", "str", 30), ("categoria", "str", 15), ("ubicacion", "point")]

# Zonas comerciales: Cercado, Miraflores, Los Olivos y La Molina (aprox.).
ZONAS = ((-12.0464, -77.0428), (-12.1193, -77.0300), (-11.9870, -77.0620), (-12.0740, -76.9550))
FRACCION_EN_ZONAS = 0.78   # el resto se reparte de forma uniforme por toda Lima
DISPERSION_GRADOS = 0.018  # desviación estándar alrededor de cada zona (≈ 2 km)


def _dentro_de_lima(lat, lon):
    lat = min(LIMA_BOUNDS["max_lat"], max(LIMA_BOUNDS["min_lat"], lat))
    lon = min(LIMA_BOUNDS["max_lon"], max(LIMA_BOUNDS["min_lon"], lon))
    return lat, lon


def generate_points(n, seed=42):
    """n comercios con ids 0..n-1: la mayoría agrupados en zonas comerciales, el resto uniforme.

    Los grupos hacen que la poda espacial importe: un radio pequeño en una zona
    densa devuelve muchos puntos y uno en las afueras, pocos.
    """
    if type(n) is not int or n < 1:
        raise ValueError("n debe ser un entero positivo")
    rng = random.Random(seed)
    rows = []
    for ident in range(n):
        if rng.random() < FRACCION_EN_ZONAS:
            lat, lon = ZONAS[ident % len(ZONAS)]
            lat += rng.gauss(0, DISPERSION_GRADOS)
            lon += rng.gauss(0, DISPERSION_GRADOS)
        else:
            lat = rng.uniform(LIMA_BOUNDS["min_lat"], LIMA_BOUNDS["max_lat"])
            lon = rng.uniform(LIMA_BOUNDS["min_lon"], LIMA_BOUNDS["max_lon"])
        lat, lon = _dentro_de_lima(lat, lon)
        categoria = CATEGORIAS[ident % len(CATEGORIAS)]
        rows.append({"id": ident, "nombre": f"{categoria}_{ident:06d}", "categoria": categoria,
                     "ubicacion": Point(lat, lon)})
    return rows


def generate_queries(n=100, seed=7):
    """Centros de consulta uniformes en Lima, comunes a todas las técnicas."""
    if type(n) is not int or n < 1:
        raise ValueError("n debe ser positivo")
    rng = random.Random(seed)
    return [{"id": i,
             "lat": rng.uniform(LIMA_BOUNDS["min_lat"], LIMA_BOUNDS["max_lat"]),
             "lon": rng.uniform(LIMA_BOUNDS["min_lon"], LIMA_BOUNDS["max_lon"])}
            for i in range(n)]


def _write_csv(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def _write_engine_sql(path, rows):
    with path.open("w", encoding="utf-8") as stream:
        stream.write("CREATE TABLE puntos (id INT PRIMARY KEY, nombre VARCHAR(30), "
                     "categoria VARCHAR(15), ubicacion POINT);\n")
        for start in range(0, len(rows), 500):
            values = ",".join(f"({r['id']},'{r['nombre']}','{r['categoria']}',"
                              f"POINT({r['ubicacion'].lat:.8f},{r['ubicacion'].lon:.8f}))"
                              for r in rows[start:start + 500])
            stream.write(f"INSERT INTO puntos VALUES {values};\n")
        stream.write("CREATE INDEX puntos_geo ON puntos (ubicacion) USING RTREE;\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", type=int, nargs="+", default=(1000, 10000, 100000))
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if any(n < 1 for n in args.sizes) or len(set(args.sizes)) != len(args.sizes):
        parser.error("--sizes debe contener enteros positivos distintos")
    args.output.mkdir(parents=True, exist_ok=True)

    for n in sorted(args.sizes):
        rows = generate_points(n, args.seed)
        _write_csv(args.output / f"puntos_{n}.csv", ("id", "nombre", "categoria", "lat", "lon"),
                   ((r["id"], r["nombre"], r["categoria"], f"{r['ubicacion'].lat:.8f}",
                     f"{r['ubicacion'].lon:.8f}") for r in rows))
        _write_csv(args.output / f"postgis_puntos_{n}.csv", ("id", "nombre", "categoria", "lon", "lat"),
                   ((r["id"], r["nombre"], r["categoria"], f"{r['ubicacion'].lon:.8f}",
                     f"{r['ubicacion'].lat:.8f}") for r in rows))
        _write_engine_sql(args.output / f"cargar_motor_{n}.sql", rows)

    queries = generate_queries(args.queries, args.seed + 1)
    with (args.output / "consultas.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("id", "lat", "lon"))
        writer.writeheader()
        writer.writerows(queries)
    metadata = {"seed": args.seed, "sizes": sorted(args.sizes), "queries": args.queries,
                "bounds": LIMA_BOUNDS, "domain": "comercios sintéticos de Lima"}
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
