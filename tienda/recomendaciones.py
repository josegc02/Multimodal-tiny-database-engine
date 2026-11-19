"""Consultas de la tienda sobre el motor de la Parte 5.

Valores medidos en benchmarks/tienda: 101 candidatos por señal, compras a 30 días
como máximo entre una y otra, y fusión RRF.
"""

CANDIDATOS = 101
VENTANA_COMPRAS = 30 * 86400  # segundos: compras.fecha está en segundos Unix
RRF_K = 60


def consultar(motor, sql):
    resultado = motor.ejecutar(sql)
    if resultado.tiene_error:
        raise RuntimeError(resultado.error)
    return [dict(zip(resultado.columnas, fila)) for fila in resultado.filas]


def compras(motor, producto_id):
    """Usuarios que compraron también otro producto, a 30 días o menos de este."""
    filas = consultar(motor, f"""
        SELECT b.producto_id AS id, COUNT(*) AS puntos
        FROM compras a JOIN compras b ON a.usuario = b.usuario
        WHERE a.producto_id = {producto_id} AND b.producto_id <> {producto_id}
          AND b.fecha <= a.fecha + {VENTANA_COMPRAS} AND b.fecha >= a.fecha - {VENTANA_COMPRAS}
        GROUP BY b.producto_id
    """)
    return {fila["id"]: fila["puntos"] for fila in filas}


def literal(texto):
    return "'" + texto.replace("'", "''") + "'"


def visual(motor, imagen):
    filas = consultar(motor, f"""
        SELECT id, SIMILARITY_SCORE() AS puntos FROM productos
        WHERE SIMILAR_TO(imagen, {literal(imagen)}, k={CANDIDATOS + 1}) USING HNSW
    """)
    return {fila["id"]: fila["puntos"] for fila in filas}


def texto(motor, descripcion):
    filas = consultar(motor, f"""
        SELECT id, SCORE() AS puntos FROM productos
        WHERE MATCH(descripcion, {literal(descripcion)}) USING BM25
        ORDER BY puntos DESC LIMIT {CANDIDATOS + 1}
    """)
    return {fila["id"]: fila["puntos"] for fila in filas}


def misma_categoria(motor, categoria, candidatos):
    """Señal "categoría similar": 1 para los candidatos de la misma categoría que el origen.

    Solo reordena lo que ya trajeron las otras señales; no agrega productos. Un
    producto sin categoría no recibe esta señal (ni bono ni castigo).
    """
    if not categoria or not candidatos:
        return {}
    filas = consultar(motor, f"SELECT id FROM productos WHERE categoria = {literal(categoria)}")
    return {fila["id"]: 1 for fila in filas if fila["id"] in candidatos}


def fusionar(origen, senales, pesos, metodo="rrf", bonos=("categoria",)):
    """Combina las señales en los 10 mejores productos.

    ``rrf`` (por defecto): cada señal aporta ``peso * (K+1) / (K+1+posición)`` con K=60,
    sin depender de la escala de sus puntajes (BM25 no tiene tope; los cosenos sí).
    Los empates de una señal se ordenan por id, que en la tienda va de más a menos
    reseñado. ``max``: cada señal dividida por su máximo positivo.
    Las señales de ``bonos`` (todas valen 1) suman su peso sin posición.
    ``puntaje`` es la media ponderada: 1 si el producto es el primero en todas.
    """
    totales = {}
    suma = sum(pesos.values())
    for nombre, puntos in senales.items():
        candidatos = sorted(((i, valor) for i, valor in puntos.items() if i != origen and valor > 0),
                            key=lambda par: (-par[1], par[0]))
        maximo = candidatos[0][1] if candidatos else 1
        for posicion, (i, valor) in enumerate(candidatos):
            if nombre in bonos:
                normalizado = 1.0
            elif metodo == "rrf":
                normalizado = (RRF_K + 1) / (RRF_K + 1 + posicion)
            else:
                normalizado = valor / maximo
            if i not in totales:
                totales[i] = {"id": i, "puntaje": 0.0, "senales": dict.fromkeys(senales, 0.0)}
            fila = totales[i]
            fila["senales"][nombre] = normalizado
            fila["puntaje"] += normalizado * (pesos[nombre] / suma)
    validos = (fila for fila in totales.values() if fila["puntaje"] > 0)
    return sorted(validos, key=lambda fila: (-fila["puntaje"], fila["id"]))[:10]


def cercanas(motor, lat, lon, producto_id=None, radio=None, limite=10):
    punto = f"POINT({lat:.12f}, {lon:.12f})"
    distancia = f"distancia(ubicacion, {punto})"
    filtro = "" if radio is None else f"WHERE {distancia} <= {radio:.8f}"
    stock = None
    if producto_id is not None:
        filas = consultar(motor, f"SELECT tienda_id, unidades FROM stock "
                                 f"WHERE producto_id = {producto_id} AND unidades > 0")
        stock = {fila["tienda_id"]: fila["unidades"] for fila in filas}
        if not stock:
            return []
    # Ampliar k si las tiendas más próximas no tienen el producto.
    k = limite
    while True:
        filas = consultar(motor, f"SELECT id, nombre, ubicacion, {distancia} AS distancia_m "
                                 f"FROM tiendas {filtro} ORDER BY {distancia} LIMIT {k}")
        if stock is None:
            return filas
        disponibles = [{**fila, "unidades": stock[fila["id"]]} for fila in filas if fila["id"] in stock]
        if len(disponibles) >= limite or len(filas) < k:
            return disponibles[:limite]
        k *= 2
