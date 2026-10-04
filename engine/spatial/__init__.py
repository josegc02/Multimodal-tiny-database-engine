"""Tipos y métricas espaciales de la Parte 2 (puntos 2D en latitud/longitud).

- geometry: Point, MBR y Polygon (issues #18 y #22).
- distance: métricas Euclidiana y Haversine, MINDIST punto-MBR (issue #19).

El índice R-Tree vive con el resto de índices en engine/indexes/rtree.py.
"""

from engine.spatial.distance import EARTH_RADIUS_M, Metric, distance, euclidean, haversine, mindist, radius_to_mbr
from engine.spatial.geometry import MBR, Point, Polygon

__all__ = [
    "EARTH_RADIUS_M", "MBR", "Metric", "Point", "Polygon",
    "distance", "euclidean", "haversine", "mindist", "radius_to_mbr",
]
