"""Consultas de la tienda sobre el motor de la Parte 5.

Valores medidos en benchmarks/tienda: 101 candidatos por señal, compras a 30 días
como máximo entre una y otra, y fusión RRF.
"""

import re

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


_PALABRAS = re.compile(r"[a-z0-9]+")
PALABRAS_CLAVE_TITULO = 6
COSENO_DUPLICADO = 0.98
# Consola o sistema; el orden importa (PS4 antes que "playstation" a secas, Wii U antes que Wii).
PLATAFORMAS = [
    ("ps5", r"\bps5\b|playstation 5"), ("ps4", r"\bps4\b|playstation 4"), ("ps3", r"\bps3\b|playstation 3"),
    ("ps2", r"\bps2\b|playstation 2"), ("psvita", r"ps ?vita|playstation vita"), ("psp", r"\bpsp\b"),
    ("xbox series", r"xbox series|series [xs]\b"), ("xbox one", r"xbox one"), ("xbox 360", r"xbox 360"),
    # "Switch" a secas también es la tecla de un teclado o el botón de un mouse ("Optical Switch"):
    # cuenta solo como consola en las formas en que se nombra a la Nintendo Switch.
    ("switch", r"nintendo[- ]?switch|\bswitch[ -]?(?:oled|lite)\b|\b(?:for|para|with)\s+(?:the\s+)?switch\b|"
               r"\bswitch\s*(?:/|console|controllers?|games?|joy-?cons?|dock|case|pro controller)|\bns\b|\bnsw\b"), ("3ds", r"\b[23]ds\b"), ("ds", r"nintendo ds\b|\bnds\b"),
    ("wii u", r"wii u\b"), ("wii", r"\bwii\b(?! u)"), ("gamecube", r"gamecube"),
    ("sega", r"\bsega\b|dreamcast|genesis|saturn"),
    ("vr", r"oculus|meta quest|\bquest [23]\b|virtual reality"), ("pc", r"\bpc\b|windows|\bmac\b|steam\b(?! deck)"),
]


def clave_titulo(titulo):
    """Las primeras palabras del título en minúsculas: agrupa colores, ediciones y relistados."""
    return " ".join(_PALABRAS.findall((titulo or "").lower())[:PALABRAS_CLAVE_TITULO])


def plataformas(titulo, categoria):
    """Consolas o sistemas del producto. Vacío si no se sabe; varias si es multiplataforma."""
    texto = f"{categoria or ''} {titulo or ''}".lower()
    return {nombre for nombre, patron in PLATAFORMAS if re.search(patron, texto)}


def misma_plataforma(origen, candidatos):
    """Señal "misma plataforma": 1 si el candidato es de la única consola del origen.

    Solo si el origen tiene exactamente una plataforma: un producto multiplataforma o
    sin plataforma conocida no da bono, y un candidato sin plataforma no se castiga.
    ``candidatos`` es {id: fila del producto}.
    """
    propias = plataformas(origen.get("titulo"), origen.get("categoria"))
    if len(propias) != 1:
        return {}
    return {i: 1 for i, fila in candidatos.items()
            if propias <= plataformas(fila.get("titulo"), fila.get("categoria"))}


def sin_duplicados(origen, ordenados, vector=None, limite=10):
    """Los primeros ``limite`` de ``ordenados`` ({id, titulo...} ya rankeados) sin duplicados.

    Duplicado: misma clave de título, o coseno de imagen > 0.98 si hay ``vector(id)``
    (unitario o None), con el producto consultado o con uno ya elegido. Se queda el
    mejor rankeado de cada grupo y se rellena con el siguiente candidato.
    """
    elegidos, claves, vectores = [], {clave_titulo(origen.get("titulo"))}, []
    v_origen = vector(origen["id"]) if vector else None
    if v_origen is not None:
        vectores.append(v_origen)
    for fila in ordenados:
        clave = clave_titulo(fila.get("titulo"))
        if clave and clave in claves:
            continue
        v = vector(fila["id"]) if vector else None
        if v is not None and any(float(v @ otro) > COSENO_DUPLICADO for otro in vectores):
            continue
        elegidos.append(fila)
        claves.add(clave)
        if v is not None:
            vectores.append(v)
        if len(elegidos) == limite:
            break
    return elegidos


def filas_por_id(motor, ids, columnas=("id", "titulo", "categoria")):
    """{id: fila} con las columnas pedidas que existan, una búsqueda por clave primaria por id.

    TEXT solo admite índices SPIMI, así que filtrar por categoría recorrería toda la
    tabla (~570 ms); ~300 búsquedas por clave primaria tardan ~100 ms. Sin la
    descripción: leerla de cada candidato sumaba ~0.3 s.
    """
    existentes = motor.catalog.table("productos").storage.schema.fields
    lista = ", ".join(c for c in columnas if c in existentes) or "*"
    filas = {}
    for i in sorted(ids):
        encontradas = consultar(motor, f"SELECT {lista} FROM productos WHERE id = {i}")
        if encontradas:
            filas[i] = encontradas[0]
    return filas


def misma_categoria(categoria, candidatos):
    """Señal "categoría similar": 1 para los candidatos de la misma categoría que el origen.

    ``candidatos`` es {id: fila}. Solo reordena lo que ya trajeron las otras señales;
    no agrega productos. Un producto sin categoría no recibe esta señal (ni bono ni castigo).
    """
    if not categoria:
        return {}
    return {i: 1 for i, fila in candidatos.items() if fila.get("categoria") == categoria}


def fusionar(origen, senales, pesos, metodo="rrf", bonos=("categoria", "plataforma"), limite=10):
    """Combina las señales en los ``limite`` mejores productos.

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
    return sorted(validos, key=lambda fila: (-fila["puntaje"], fila["id"]))[:limite]


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
    existentes = motor.catalog.table("tiendas").storage.schema.fields
    columnas = ", ".join(c for c in ("id", "nombre", "distrito", "direccion", "ubicacion") if c in existentes)
    # Ampliar k si las tiendas más próximas no tienen el producto.
    k = limite
    while True:
        filas = consultar(motor, f"SELECT {columnas}, {distancia} AS distancia_m "
                                 f"FROM tiendas {filtro} ORDER BY {distancia} LIMIT {k}")
        if stock is None:
            return filas
        disponibles = [{**fila, "unidades": stock[fila["id"]]} for fila in filas if fila["id"] in stock]
        if len(disponibles) >= limite or len(filas) < k:
            return disponibles[:limite]
        k *= 2
