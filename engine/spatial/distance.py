"""Distancias en metros: Euclidiana (lat/lon como plano) y geodésica (Haversine).

- EUCLIDEAN: distancia en el plano (lat, lon) convertida de grados a metros con
  un factor fijo. Exacta en dirección norte-sur; en dirección este-oeste
  sobreestima por 1/cos(lat) (≈ 2,2% en Lima).
- HAVERSINE: gran círculo sobre una esfera de radio EARTH_RADIUS_M.

MINDIST(punto, MBR) es la menor distancia posible del punto a cualquier punto
del rectángulo: el R-Tree la usa para podar nodos en rango y k-NN.
"""

from __future__ import annotations

import math
from enum import Enum

from engine.spatial.geometry import MBR, Point

EARTH_RADIUS_M = 6_371_008.8                         # radio medio (IUGG)
METERS_PER_DEGREE = EARTH_RADIUS_M * math.pi / 180   # ≈ 111 195 m
BOX_MARGIN_DEG = 1e-9                                # ≈ 0,1 mm: absorbe errores de redondeo


class Metric(str, Enum):
    EUCLIDEAN = "euclidean"
    HAVERSINE = "haversine"


def euclidean(a: Point, b: Point) -> float:
    return math.hypot(a.lat - b.lat, a.lon - b.lon) * METERS_PER_DEGREE


def haversine(a: Point, b: Point) -> float:
    return _haversine(a.lat, a.lon, b.lat, b.lon)


def _haversine(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def distance(a: Point, b: Point, metric: Metric = Metric.HAVERSINE) -> float:
    if metric is Metric.EUCLIDEAN:
        return euclidean(a, b)
    if metric is Metric.HAVERSINE:
        return haversine(a, b)
    raise ValueError(f"Métrica no soportada: {metric!r}")


def mindist(point: Point, mbr: MBR, metric: Metric = Metric.HAVERSINE) -> float:
    """Distancia mínima del punto al rectángulo; 0 si está dentro o en el borde."""
    if metric is Metric.EUCLIDEAN:
        # En el plano el punto más cercano se obtiene acotando cada coordenada.
        lat = min(max(point.lat, mbr.min_lat), mbr.max_lat)
        lon = min(max(point.lon, mbr.min_lon), mbr.max_lon)
        return math.hypot(point.lat - lat, point.lon - lon) * METERS_PER_DEGREE
    if metric is not Metric.HAVERSINE:
        raise ValueError(f"Métrica no soportada: {metric!r}")

    if mbr.min_lon <= point.lon <= mbr.max_lon:
        # Dentro de la franja de longitudes: lo más cercano está sobre el mismo meridiano.
        lat = min(max(point.lat, mbr.min_lat), mbr.max_lat)
        return _haversine(point.lat, point.lon, lat, point.lon)

    # Fuera de la franja: lo más cercano está sobre el meridiano del borde más próximo
    # (contando la vuelta por el antimeridiano).
    to_west = (mbr.min_lon - point.lon) % 360
    to_east = (point.lon - mbr.max_lon) % 360
    edge_lon, delta = (mbr.min_lon, to_west) if to_west <= to_east else (mbr.max_lon, to_east)
    # Sobre ese meridiano la distancia es mínima en `closest`. Si esa latitud cae fuera
    # del borde, el mínimo está en uno de sus extremos.
    closest = math.degrees(math.atan2(math.tan(math.radians(point.lat)), math.cos(math.radians(delta))))
    candidates = (min(max(closest, mbr.min_lat), mbr.max_lat), mbr.min_lat, mbr.max_lat)
    return min(_haversine(point.lat, point.lon, lat, edge_lon) for lat in candidates)


def radius_to_mbr(center: Point, radius_m: float, metric: Metric = Metric.HAVERSINE) -> MBR:
    """Rectángulo que contiene todos los puntos a `radius_m` metros o menos (filtro grueso).

    Si el círculo toca un polo o cruza el antimeridiano se devuelve la franja
    completa de longitudes: es más grande de lo necesario, pero nunca pierde puntos.
    """
    if type(radius_m) not in (int, float) or not math.isfinite(radius_m) or radius_m < 0:
        raise ValueError(f"El radio debe ser un número no negativo: {radius_m!r}")

    if metric is Metric.EUCLIDEAN:
        dlat = dlon = radius_m / METERS_PER_DEGREE
    elif metric is Metric.HAVERSINE:
        angle = radius_m / EARTH_RADIUS_M
        if angle >= math.pi:
            return MBR(-90.0, -180.0, 90.0, 180.0)
        dlat = math.degrees(angle)
        if abs(center.lat) + dlat >= 90:
            dlon = 180.0
        else:
            # Mayor diferencia de longitud del círculo (en la latitud donde es tangente).
            dlon = math.degrees(math.asin(math.sin(angle) / math.cos(math.radians(center.lat))))
    else:
        raise ValueError(f"Métrica no soportada: {metric!r}")

    dlat, dlon = dlat + BOX_MARGIN_DEG, dlon + BOX_MARGIN_DEG
    min_lat, max_lat = max(-90.0, center.lat - dlat), min(90.0, center.lat + dlat)
    min_lon, max_lon = center.lon - dlon, center.lon + dlon
    if min_lon < -180 or max_lon > 180:
        min_lon, max_lon = -180.0, 180.0
    return MBR(min_lat, min_lon, max_lat, max_lon)
