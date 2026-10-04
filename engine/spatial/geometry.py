"""Geometrías 2D: punto, rectángulo mínimo (MBR) y polígono.

Convención de coordenadas: POINT(lat, lon), como en el enunciado
(`POINT(-12.0464, -77.0428)` es Lima). PostGIS usa el orden inverso
(`ST_MakePoint(lon, lat)`); tenerlo en cuenta al comparar con GiST (issue #26).

Estado: estructura base. Los métodos marcados como pendientes se implementan
en los issues indicados.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Point:
    """Punto geográfico en grados decimales: lat ∈ [-90, 90], lon ∈ [-180, 180]."""

    lat: float
    lon: float

    def validate(self) -> None:
        """Rechaza coordenadas fuera de rango o no finitas. Pendiente: issue #18."""
        raise NotImplementedError("Pendiente: issue #18")


@dataclass(frozen=True)
class MBR:
    """Minimum Bounding Rectangle alineado a los ejes (en grados)."""

    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    @classmethod
    def from_point(cls, point: Point) -> MBR:
        """MBR degenerado de un punto. Pendiente: issue #18."""
        raise NotImplementedError("Pendiente: issue #18")

    def area(self) -> float:
        """Área en grados² (criterio de ChooseLeaf y del split). Pendiente: issue #18."""
        raise NotImplementedError("Pendiente: issue #18")

    def union(self, other: MBR) -> MBR:
        """MBR mínimo que contiene a ambos. Pendiente: issue #18."""
        raise NotImplementedError("Pendiente: issue #18")

    def enlargement(self, other: MBR) -> float:
        """Aumento de área al incluir `other` (ChooseLeaf). Pendiente: issue #18."""
        raise NotImplementedError("Pendiente: issue #18")

    def intersects(self, other: MBR) -> bool:
        """¿Los rectángulos se tocan o solapan? Pendiente: issue #20."""
        raise NotImplementedError("Pendiente: issue #20")

    def contains_point(self, point: Point) -> bool:
        """¿El punto cae dentro o en el borde? Pendiente: issue #20."""
        raise NotImplementedError("Pendiente: issue #20")


@dataclass(frozen=True)
class Polygon:
    """Polígono simple (sin agujeros) dado por sus vértices en orden.

    No hace falta repetir el primer vértice al final.
    """

    vertices: Sequence[Point]

    def mbr(self) -> MBR:
        """MBR del polígono (filtro grueso en el R-Tree). Pendiente: issue #22."""
        raise NotImplementedError("Pendiente: issue #22")

    def contains(self, point: Point) -> bool:
        """Point-in-polygon por ray casting (refinamiento). Pendiente: issue #22.

        Definir y documentar qué pasa con los puntos sobre el borde.
        """
        raise NotImplementedError("Pendiente: issue #22")

    @classmethod
    def from_geojson(cls, geometry: dict) -> list[Polygon]:
        """Polígonos de una geometría GeoJSON (Polygon o MultiPolygon). Pendiente: issue #22.

        GeoJSON guarda [lon, lat]: invertir el orden al construir cada Point.
        """
        raise NotImplementedError("Pendiente: issue #22")
