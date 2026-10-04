"""Datasets espaciales reproducibles para la Parte 2 (issue #25).

Uso previsto:
    python benchmarks/generate_spatial_datasets.py --sizes 1000 10000 100000

Escribe en datasets/spatial/generated/ (ignorado por git):
- puntos_<N>.csv con columnas id, nombre, categoria, lat, lon;
- consultas.csv con los 100 puntos de consulta comunes a todas las técnicas.

Los polígonos de distritos (GeoJSON) van en datasets/spatial/ (ver su README).
Estado: estructura base.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "datasets" / "spatial" / "generated"

# Rectángulo aproximado de Lima Metropolitana (lat, lon). Ajustar si se usan
# datos reales de OpenStreetMap o el contorno de los distritos.
LIMA_BOUNDS = {"min_lat": -12.30, "max_lat": -11.75, "min_lon": -77.20, "max_lon": -76.80}
CATEGORIAS = ("tienda", "restaurante", "gasolinera", "farmacia", "banco")
SCHEMA = [("id", "int"), ("nombre", "str", 30), ("categoria", "str", 15), ("ubicacion", "point")]


def generate_points(n: int, seed: int = 42) -> List[Dict[str, Any]]:
    """n puntos dentro de LIMA_BOUNDS con IDs 0..n-1. Pendiente: issue #25.

    Decidir la distribución: uniforme, o con concentraciones (clusters) que
    imiten zonas comerciales; con clusters, el R-Tree se diferencia más del scan.
    """
    raise NotImplementedError("Pendiente: issue #25")


def generate_queries(n: int = 100, seed: int = 7) -> List[Dict[str, float]]:
    """Puntos de consulta comunes a todas las técnicas. Pendiente: issue #25."""
    raise NotImplementedError("Pendiente: issue #25")


def main() -> None:
    raise NotImplementedError("Pendiente: issue #25")


if __name__ == "__main__":
    main()
