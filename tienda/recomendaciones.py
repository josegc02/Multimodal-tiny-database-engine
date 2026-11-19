"""Consultas de la tienda sobre el motor de la Parte 5."""


def consultar(motor, sql):
    resultado = motor.ejecutar(sql)
    if resultado.tiene_error:
        raise RuntimeError(resultado.error)
    return [dict(zip(resultado.columnas, fila)) for fila in resultado.filas]


def compras(motor, producto_id):
    filas = consultar(motor, f"""
        SELECT b.producto_id AS id, COUNT(*) AS puntos
        FROM compras a JOIN compras b ON a.usuario = b.usuario
        WHERE a.producto_id = {producto_id} AND b.producto_id <> {producto_id}
        GROUP BY b.producto_id
    """)
    return {fila["id"]: fila["puntos"] for fila in filas}


def literal(texto):
    return "'" + texto.replace("'", "''") + "'"


def visual(motor, imagen):
    filas = consultar(motor, f"""
        SELECT id, SIMILARITY_SCORE() AS puntos FROM productos
        WHERE SIMILAR_TO(imagen, {literal(imagen)}, k=51) USING HNSW
    """)
    return {fila["id"]: fila["puntos"] for fila in filas}


def texto(motor, descripcion):
    filas = consultar(motor, f"""
        SELECT id, SCORE() AS puntos FROM productos
        WHERE MATCH(descripcion, {literal(descripcion)}) USING BM25
        ORDER BY puntos DESC LIMIT 51
    """)
    return {fila["id"]: fila["puntos"] for fila in filas}
