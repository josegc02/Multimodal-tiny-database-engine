"""Datos que el panel de mapa necesita de una consulta: puntos, resultados y figuras."""

from engine.query import ast
from engine.spatial.geometry import Point, Polygon

# Desde este tamaño de tabla solo se dibujan los resultados, no el contexto.
LIMITE_CONTEXTO = 100
# Cada marcador es texto y canvas en el hilo de Tk: más que esto congela la ventana.
MAX_MARCADORES = 500
MARGEN_ENCUADRE = 0.1
LADO_MINIMO_ENCUADRE = 0.002


def columna_punto(binding):
    """Primera columna POINT de la tabla, o None."""
    schema = binding.storage.schema
    return next((name for name, kind in zip(schema.fields, schema.types) if kind == "point"), None)


def identificador(binding):
    return binding.primary_key or binding.storage.schema.fields[0]


def puntos_de_tabla(binding, columna):
    """[(id, lat, lon, etiqueta)] de toda la tabla (un scan)."""
    ident = identificador(binding)
    return [(record[ident], record[columna].lat, record[columna].lon, f"{record[ident]}")
            for _, record in binding.storage.scan()]


def ids_resultado(rows, ident):
    """Identificadores presentes en las filas del resultado (columna `id` o `t.id`)."""
    return sorted({value for row in rows for key, value in row.items()
                   if key == ident or key.endswith("." + ident)}, key=repr)


def figuras(where):
    """Centro y radio de `distancia(...) < r` y polígono de `WITHIN`, en cualquier parte del WHERE."""
    circle, polygon = None, None
    pending = [where]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.BinaryOp):
            if node.operator in ("<", "<=", ">", ">="):
                for call, other in ((node.left, node.right), (node.right, node.left)):
                    center = _centro(call)
                    if center and isinstance(other, ast.Literal) and type(other.value) in (int, float):
                        circle = {"lat": center.lat, "lon": center.lon, "radius": other.value}
            pending += [node.left, node.right]
        elif isinstance(node, ast.UnaryOp):
            pending.append(node.operand)
        elif isinstance(node, ast.SpatialCall):
            center = _centro(node)
            if center and circle is None:
                circle = {"lat": center.lat, "lon": center.lon, "radius": 0}
            shape = next((a.value for a in node.arguments
                          if isinstance(a, ast.Literal) and isinstance(a.value, Polygon)), None)
            if node.function == "WITHIN" and shape:
                polygon = [(p.lat, p.lon) for p in shape.vertices]
    return circle, polygon


def centro_knn(statement):
    """Punto de `ORDER BY distancia(col, POINT(...))`, si lo hay."""
    for item in statement.order_by or ():
        center = _centro(item.expression)
        if center:
            return {"lat": center.lat, "lon": center.lon, "radius": 0}
    return None


def seleccionar_puntos(points, result_ids):
    """Puntos a dibujar: sin contexto en tablas grandes y nunca más de MAX_MARCADORES."""
    if len(points) >= LIMITE_CONTEXTO:
        points = [p for p in points if p[0] in result_ids]
    return points[:MAX_MARCADORES]


def encuadre(coordenadas):
    """Esquinas (arriba-izquierda, abajo-derecha) que contienen las coordenadas, o None."""
    if not coordenadas:
        return None
    lats = [lat for lat, _ in coordenadas]
    lons = [lon for _, lon in coordenadas]
    lat_centro, lon_centro = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    # Un solo punto no tiene extensión: el lado mínimo fija el zoom máximo.
    medio_alto = max(max(lats) - min(lats), LADO_MINIMO_ENCUADRE) * (0.5 + MARGEN_ENCUADRE)
    medio_ancho = max(max(lons) - min(lons), LADO_MINIMO_ENCUADRE) * (0.5 + MARGEN_ENCUADRE)
    return ((lat_centro + medio_alto, lon_centro - medio_ancho),
            (lat_centro - medio_alto, lon_centro + medio_ancho))


def _centro(expression):
    if isinstance(expression, ast.SpatialCall) and expression.function == "DISTANCIA":
        return next((a.value for a in expression.arguments
                     if isinstance(a, ast.Literal) and isinstance(a.value, Point)), None)
    return None
