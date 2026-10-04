"""Geometrías 2D en grados: punto, rectángulo mínimo (MBR) y polígono.

Orden de coordenadas: POINT(lat, lon), como en el enunciado. PostGIS y GeoJSON
usan (lon, lat).
"""

from __future__ import annotations

import math
import json
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
    """Anillos planos en lat/lon, con bordes incluidos y agujeros opcionales.

    No interpreta cruces del antimeridiano. Se normalizan los anillos cerrados
    a tuplas sin repetir el primer vértice, independientes del sentido de giro.
    """

    vertices: Sequence[Point]
    holes: tuple = ()

    def __post_init__(self):
        def ring(values):
            values = tuple(values)
            if values and values[0] == values[-1]:
                values = values[:-1]
            if any(not isinstance(p, Point) for p in values):
                raise ValueError("Los vértices deben ser Point")
            if len(values) < 3 or len(set(values)) != len(values):
                raise ValueError("Un anillo necesita al menos tres vértices distintos")
            origin = values[0]
            area = sum((a.lon - origin.lon) * (b.lat - origin.lat)
                       - (b.lon - origin.lon) * (a.lat - origin.lat)
                       for a, b in zip(values, values[1:] + values[:1]))
            if area == 0:
                raise ValueError("El anillo tiene área cero")
            return values
        object.__setattr__(self, "vertices", ring(self.vertices))
        object.__setattr__(self, "holes", tuple(ring(hole) for hole in self.holes))

    def mbr(self) -> MBR:
        return MBR.of_points(self.vertices)

    @staticmethod
    def _ring_location(vertices, point):
        """0 fuera, 1 dentro, 2 borde. Ray casting con intervalos semiabiertos."""
        inside = False
        x, y = point.lon, point.lat
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            dx, dy = b.lon - a.lon, b.lat - a.lat
            cross = dx * (y - a.lat) - dy * (x - a.lon)
            if (abs(cross) <= 1e-12 * max(abs(dx), abs(dy))
                    and min(a.lon, b.lon) <= x <= max(a.lon, b.lon)
                    and min(a.lat, b.lat) <= y <= max(a.lat, b.lat)):
                return 2
            if (a.lat > y) != (b.lat > y) and x < a.lon + (y - a.lat) * dx / dy:
                inside = not inside
        return int(inside)

    def contains(self, point: Point) -> bool:
        """Incluye el contorno exterior y bordes de agujeros; excluye su interior."""
        if not self.mbr().contains_point(point):
            return False
        outer = self._ring_location(self.vertices, point)
        if outer != 1:
            return outer == 2
        for hole in self.holes:
            location = self._ring_location(hole, point)
            if location == 2:
                return True
            if location == 1:
                return False
        return True

    @classmethod
    def from_geojson(cls, geometry: dict) -> list[Polygon]:
        """Polygon/MultiPolygon, Feature o FeatureCollection ([lon, lat])."""
        if not isinstance(geometry, dict):
            raise ValueError("Se esperaba un objeto GeoJSON")
        kind = geometry.get("type")
        if kind == "Feature":
            return cls.from_geojson(geometry.get("geometry"))
        if kind == "FeatureCollection":
            return [polygon for feature in geometry.get("features", [])
                    for polygon in cls.from_geojson(feature)]
        if kind not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"Geometría GeoJSON no soportada: {kind!r}")
        try:
            coordinates = geometry["coordinates"]
            polygons = [coordinates] if kind == "Polygon" else coordinates
            result = []
            for rings in polygons:
                converted = [tuple(Point(position[1], position[0]) for position in ring) for ring in rings]
                if not converted:
                    raise ValueError("Polígono GeoJSON vacío")
                result.append(cls(converted[0], tuple(converted[1:])))
            return result
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Coordenadas GeoJSON inválidas") from exc


def load_districts(path, name_field="nombre") -> dict[str, tuple[Polygon, ...]]:
    """Carga una FeatureCollection y agrupa polígonos por nombre de distrito.

    `name_field` permite usar propiedades de datasets reales como NOMB_DIST.
    Conserva componentes de MultiPolygon y agujeros, sin intercambiar lat/lon.
    """
    with open(path, encoding="utf-8-sig") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ValueError("Se esperaba una FeatureCollection de distritos")
    districts = {}
    for feature in data.get("features", []):
        name = (feature.get("properties") or {}).get(name_field)
        if not isinstance(name, str) or not name:
            raise ValueError(f"Falta el nombre del distrito en {name_field!r}")
        districts[name] = districts.get(name, ()) + tuple(Polygon.from_geojson(feature))
    return districts
