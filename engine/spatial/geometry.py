"""Geometrías 2D en grados: punto, rectángulo mínimo (MBR) y polígono.

Orden de coordenadas: POINT(lat, lon), como en el enunciado. PostGIS y GeoJSON
usan (lon, lat).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence


def _coordinate(value, low, high, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} debe ser un número entre {low} y {high}: {value!r}")


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float

    def __post_init__(self):
        _coordinate(self.lat, -90, 90, "lat")
        _coordinate(self.lon, -180, 180, "lon")


@dataclass(frozen=True)
class MBR:
    """Rectángulo alineado a los ejes. No cruza el antimeridiano (min_lon <= max_lon)."""

    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    def __post_init__(self):
        _coordinate(self.min_lat, -90, 90, "min_lat")
        _coordinate(self.max_lat, -90, 90, "max_lat")
        _coordinate(self.min_lon, -180, 180, "min_lon")
        _coordinate(self.max_lon, -180, 180, "max_lon")
        if self.min_lat > self.max_lat or self.min_lon > self.max_lon:
            raise ValueError(f"MBR inválido: los mínimos superan a los máximos ({self})")

    @classmethod
    def from_point(cls, point: Point) -> MBR:
        return cls(point.lat, point.lon, point.lat, point.lon)

    @classmethod
    def of_points(cls, points: Iterable[Point]) -> MBR:
        points = list(points)
        if not points:
            raise ValueError("Se necesita al menos un punto")
        lats = [p.lat for p in points]
        lons = [p.lon for p in points]
        return cls(min(lats), min(lons), max(lats), max(lons))

    def area(self) -> float:
        """Área en grados² (criterio de ChooseLeaf y del split)."""
        return (self.max_lat - self.min_lat) * (self.max_lon - self.min_lon)

    def margin(self) -> float:
        """Semiperímetro en grados (desempata splits con área 0, p. ej. puntos alineados)."""
        return (self.max_lat - self.min_lat) + (self.max_lon - self.min_lon)

    def union(self, other: MBR) -> MBR:
        return MBR(min(self.min_lat, other.min_lat), min(self.min_lon, other.min_lon),
                   max(self.max_lat, other.max_lat), max(self.max_lon, other.max_lon))

    def enlargement(self, other: MBR) -> float:
        """Cuánto crece el área si se incluye `other`."""
        return self.union(other).area() - self.area()

    def intersects(self, other: MBR) -> bool:
        """Verdadero si se solapan o se tocan en un borde."""
        return (self.min_lat <= other.max_lat and other.min_lat <= self.max_lat
                and self.min_lon <= other.max_lon and other.min_lon <= self.max_lon)

    def overlap(self, other: MBR) -> float:
        """Área de la intersección (0 si no se solapan)."""
        height = min(self.max_lat, other.max_lat) - max(self.min_lat, other.min_lat)
        width = min(self.max_lon, other.max_lon) - max(self.min_lon, other.min_lon)
        return height * width if height > 0 and width > 0 else 0.0

    def contains_point(self, point: Point) -> bool:
        """Verdadero si el punto está dentro o sobre el borde."""
        return self.min_lat <= point.lat <= self.max_lat and self.min_lon <= point.lon <= self.max_lon


@dataclass(frozen=True)
class Polygon:
    """Polígono simple (sin agujeros), vértices en orden y sin repetir el primero."""

    vertices: Sequence[Point]

    def mbr(self) -> MBR:
        raise NotImplementedError("Pendiente: issue #22")

    def contains(self, point: Point) -> bool:
        """Point-in-polygon por ray casting."""
        raise NotImplementedError("Pendiente: issue #22")

    @classmethod
    def from_geojson(cls, geometry: dict) -> list[Polygon]:
        """Polygon o MultiPolygon de GeoJSON ([lon, lat])."""
        raise NotImplementedError("Pendiente: issue #22")
