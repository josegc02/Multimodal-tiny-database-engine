"""Métricas de distancia Euclidiana y geodésica (Haversine), en metros.

Las dos devuelven metros para que `distancia(col, POINT(...)) < 5000` tenga el
mismo significado con cualquier métrica (issue #23):

- HAVERSINE: distancia sobre la esfera de radio EARTH_RADIUS_M.
- EUCLIDEAN: distancia en el plano tratando lat/lon como coordenadas
  cartesianas (decisión pendiente del issue #19: grados escalados a metros con
  una proyección equirectangular, o grados sin escalar). Documentar el error
  frente a Haversine según la latitud y la distancia.

MINDIST(punto, MBR) es la cota inferior de la distancia del punto a cualquier
punto del rectángulo; el R-Tree la usa para podar en rango y k-NN.

Estado: estructura base.
"""

from __future__ import annotations

from enum import Enum

from engine.spatial.geometry import MBR, Point

# Radio medio de la Tierra (IUGG), el mismo que suelen usar los ejemplos de PostGIS.
EARTH_RADIUS_M = 6_371_008.8


class Metric(str, Enum):
    """Métrica elegida en SQL con USING EUCLIDEAN | HAVERSINE (issue #23)."""

    EUCLIDEAN = "euclidean"
    HAVERSINE = "haversine"


def euclidean(a: Point, b: Point) -> float:
    """Distancia euclidiana en metros. Pendiente: issue #19."""
    raise NotImplementedError("Pendiente: issue #19")


def haversine(a: Point, b: Point) -> float:
    """Distancia geodésica (gran círculo) en metros. Pendiente: issue #19.

    Prueba de referencia sugerida: Lima - Cusco ≈ 574 km.
    """
    raise NotImplementedError("Pendiente: issue #19")


def distance(a: Point, b: Point, metric: Metric = Metric.HAVERSINE) -> float:
    """Despacha a la métrica pedida."""
    if metric is Metric.EUCLIDEAN:
        return euclidean(a, b)
    if metric is Metric.HAVERSINE:
        return haversine(a, b)
    raise ValueError(f"Métrica no soportada: {metric!r}")


def mindist(point: Point, mbr: MBR, metric: Metric = Metric.HAVERSINE) -> float:
    """Cota inferior de la distancia del punto al rectángulo (0 si está dentro). Pendiente: issue #19."""
    raise NotImplementedError("Pendiente: issue #19")


def radius_to_mbr(center: Point, radius_m: float) -> MBR:
    """MBR en grados que contiene el círculo de `radius_m` metros (filtro grueso). Pendiente: issue #19.

    Cuidar el ensanche de la longitud con la latitud (1° de lon ≈ 111 km · cos(lat))
    y los polos y el antimeridiano.
    """
    raise NotImplementedError("Pendiente: issue #19")
