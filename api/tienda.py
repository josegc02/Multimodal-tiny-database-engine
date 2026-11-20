"""API de catálogo, recomendaciones y tiendas."""
import math
import threading
from typing import Literal
from tienda.indice_imagen import ImageIndex

from fastapi import APIRouter, HTTPException, Query

import numpy as np

from tienda.busqueda import ampliar

from tienda.recomendaciones import (CANDIDATOS, cercanas, compras, consultar, filas_por_id, fusionar, literal,
                                    misma_categoria, misma_plataforma, sin_duplicados, texto, visual)

# Pesos medidos en benchmarks/tienda con dos métricas (tipo de producto y co-compras
# posteriores), elegidos en validación y reportados en prueba con fusión RRF.
PESOS = "1,0.5,1"
PESO_CATEGORIA = 0.25
PESO_PLATAFORMA = 0.5  # misma consola de 75 % a 93 %; elegido con las métricas de tipo y comportamiento


def compras_en_cache(estado, motor, producto_id):
    """"También compraron" de un producto, calculado una sola vez.

    El producto más comprado tarda ~0.6 s; el resultado solo cambia si cambian las
    compras. El motor reemplaza las estadísticas de la tabla en cada INSERT, DELETE o
    UPDATE, así que un objeto de estadísticas distinto invalida la caché. Llamar con el
    lock del motor tomado.
    """
    stats = motor.catalog.table("compras").statistics
    cache = estado.get("cache_compras")
    if cache is None or cache["stats"] is not stats:
        cache = estado["cache_compras"] = {"stats": stats, "datos": {}}
    if producto_id not in cache["datos"]:
        cache["datos"][producto_id] = compras(motor, producto_id)
    return cache["datos"][producto_id]


def indice_mobilenet(estado):
    """El índice MobileNet de la API; se crea una sola vez (no en cada petición)."""
    if "indice_mobilenet" not in estado:
        estado["indice_mobilenet"] = ImageIndex(estado["motor"].directorio)
    return estado["indice_mobilenet"]


def revisar_en_segundo_plano(estado, lock):
    """Revisa las imágenes de MobileNet sin que ninguna petición espere (una revisión a la vez)."""
    if estado.get("revisando_mobilenet"):
        return None
    estado["revisando_mobilenet"] = True

    def trabajo():
        try:
            with lock:
                filas = consultar(estado["motor"], "SELECT id, imagen FROM productos")
            indice_mobilenet(estado).actualizar(filas)
        except (OSError, ValueError, RuntimeError, KeyError):
            pass  # la próxima petición lo vuelve a intentar
        finally:
            estado["revisando_mobilenet"] = False

    hilo = threading.Thread(target=trabajo, name="revisar-mobilenet", daemon=True)
    hilo.start()
    return hilo


def precalentar(estado, lock):
    """Construye el índice MobileNet en segundo plano al iniciar la API.

    Así la primera recomendación no espera ~45 s a que se arme el grafo. Solo si
    la tienda ya está cargada; si falta el modelo, la API recomienda con SIFT.
    """
    def trabajo():
        try:
            with lock:
                motor = estado["motor"]
                if "productos" not in motor.catalog.tables:
                    return
                filas = consultar(motor, "SELECT id, imagen FROM productos")
            indice_mobilenet(estado).actualizar(filas)
        except (OSError, ValueError, RuntimeError, KeyError):
            pass  # sin modelo o sin tienda: la primera petición decide

    hilo = threading.Thread(target=trabajo, name="precalentar-mobilenet", daemon=True)
    hilo.start()
    return hilo


def rutas_tienda(estado, lock):
    router = APIRouter()

    def producto(motor, identificador):
        filas = consultar(motor, f"SELECT * FROM productos WHERE id = {identificador}")
        if not filas:
            raise HTTPException(404, "Producto inexistente")
        return filas[0]

    @router.get("/catalogo")
    def catalogo(categoria: str | None = None, q: str | None = None,
                 precio_min: float | None = Query(None, ge=0, allow_inf_nan=False),
                 precio_max: float | None = Query(None, ge=0, allow_inf_nan=False),
                 limite: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        filtros = []
        if categoria:
            # La categoría y sus subcategorías: "Video Games > PlayStation 4" incluye "... > Games".
            filtros.append(f"(categoria = {literal(categoria)} OR categoria LIKE {literal(categoria.replace('%', '') + ' > %')})")
        if precio_min is not None and precio_max is not None and precio_min > precio_max:
            raise HTTPException(422, "Rango de precios invertido")
        for operador, valor in ((">=", precio_min), ("<=", precio_max)):
            if valor is not None:
                filtros.append(f"precio {operador} {valor:.12f}")
        if q:
            # Las descripciones están en inglés: "mando inalámbrico" también busca "controller wireless".
            filtros.append(f"MATCH(descripcion, {literal(ampliar(q))}) USING BM25")
        where = " WHERE " + " AND ".join(filtros) if filtros else ""
        # Con búsqueda, por relevancia BM25. Sin ella, en el orden de carga del archivo, que es
        # el de id (los productos se cargan de más a menos reseñados): el índice de la clave
        # primaria es hash y no da orden, y ORDER BY id ordenaba las 7,995 filas para mostrar
        # 24 (1.5 s frente a 0.2 s leyendo las primeras que cumplen el filtro).
        orden = " ORDER BY SCORE() DESC, id" if q else ""
        with lock:
            return consultar(estado["motor"], f"SELECT * FROM productos{where}{orden} "
                             f"LIMIT {limite} OFFSET {offset}")

    @router.get("/categorias")
    def categorias():
        """Cada categoría con su cantidad de productos, de mayor a menor.

        El GROUP BY recorre los 7,995 productos (~1.9 s): se guarda y se recalcula solo si
        cambia la tabla, que el motor señala reemplazando sus estadísticas.
        """
        with lock:
            motor = estado["motor"]
            stats = motor.catalog.table("productos").statistics
            cache = estado.get("cache_categorias")
            if cache is None or cache[0] is not stats:
                filas = consultar(motor, "SELECT categoria, COUNT(*) AS productos FROM productos GROUP BY categoria")
                cache = estado["cache_categorias"] = (stats, sorted(filas, key=lambda f: (-f["productos"], f["categoria"] or "")))
        return cache[1]

    @router.get("/productos/{id}")
    def ficha(id: int, lat: float | None = Query(None, ge=-90, le=90),
              lon: float | None = Query(None, ge=-180, le=180)):
        if (lat is None) != (lon is None):
            raise HTTPException(422, "Indique lat y lon juntas")
        with lock:
            motor = estado["motor"]
            fila = producto(motor, id)
            if lat is not None:
                tiendas = cercanas(motor, lat, lon, id, limite=1)
                fila["tienda_cercana"] = next(iter(tiendas), None)
            return fila

    @router.get("/recomendaciones/{id}")
    def recomendaciones(id: int, pesos: str = Query(PESOS, description="Compras, imagen, texto"),
                        vector_imagen: Literal["sift", "mobilenet"] | None = Query(
                            None, description="Por defecto mobilenet; si falta el modelo, sift"),
                        peso_categoria: float = Query(PESO_CATEGORIA, ge=0, allow_inf_nan=False),
                        peso_plataforma: float = Query(PESO_PLATAFORMA, ge=0, allow_inf_nan=False),
                        duplicados: bool = Query(False, description="True deja los duplicados (otro color, relistado)"),
                        fusion: Literal["rrf", "max"] = "rrf"):
        try:
            valores = [float(p) for p in pesos.split(",")]
        except ValueError:
            valores = []
        if (len(valores) != 3 or any(p < 0 for p in valores)
                or not math.isfinite(sum(valores)) or sum(valores) <= 0):
            raise HTTPException(422, "Indique tres pesos no negativos con suma positiva y finita")
        usar_mobilenet = vector_imagen != "sift"
        indice = indice_mobilenet(estado) if usar_mobilenet else None
        # Con un índice ya armado, una revisión vencida corre en segundo plano y se responde
        # con el índice actual; solo sin índice (primera vez) la petición espera.
        revisar = usar_mobilenet and indice.index is None
        if usar_mobilenet and indice.index is not None and not indice.vigente():
            if indice.REVISAR_EN_SEGUNDO_PLANO:
                revisar_en_segundo_plano(estado, lock)
            else:
                revisar = True
        with lock:
            motor = estado["motor"]
            origen = producto(motor, id)
            catalogo_imagenes = consultar(motor, "SELECT id, imagen FROM productos") if revisar else None
        if usar_mobilenet:
            # Fuera del lock del motor: extraer el catálogo tarda minutos la primera vez y
            # no debe congelar el resto de la API. El índice tiene su propio lock.
            try:
                if revisar:
                    indice.actualizar(catalogo_imagenes)
                imagen = indice.buscar(id, k=CANDIDATOS + 1)  # vacío si el producto no tiene vector: quedan compras y texto
            except (OSError, ValueError) as exc:  # falta el modelo: afecta a todo el índice
                if vector_imagen == "mobilenet":
                    raise HTTPException(503, str(exc)) from exc
                usar_mobilenet = False  # por defecto: se recomienda con SIFT
        with lock:
            motor = estado["motor"]
            if not usar_mobilenet:
                imagen = visual(motor, origen["imagen"])
            senales = {"compras": compras_en_cache(estado, motor, id), "imagen": imagen,
                       "texto": texto(motor, origen["descripcion"])}
            pesos_senales = dict(zip(senales, valores))
            if peso_categoria > 0 or peso_plataforma > 0:
                # Solo los candidatos de señales con peso: una señal apagada no aporta productos.
                candidatos = filas_por_id(motor, {i for nombre, puntos in senales.items() if pesos_senales[nombre] > 0
                                                  for i, valor in puntos.items() if valor > 0} - {id})
                if peso_categoria > 0:
                    senales["categoria"] = misma_categoria(origen.get("categoria"), candidatos)
                    pesos_senales["categoria"] = peso_categoria
                if peso_plataforma > 0:
                    senales["plataforma"] = misma_plataforma(origen, candidatos)
                    pesos_senales["plataforma"] = peso_plataforma
            filas = fusionar(id, senales, pesos_senales, fusion, limite=10 if duplicados else 60)
            filas = [{**producto(motor, fila["id"]), **fila} for fila in filas]
        if not duplicados:
            vectores = indice.index.vectors if usar_mobilenet and indice.index is not None else {}

            def vector(i):
                v = vectores.get(i)
                return None if v is None else v / (np.linalg.norm(v) or 1)
            filas = sin_duplicados(origen, filas, vector)
        return filas

    @router.get("/tiendas/cercanas")
    def tiendas(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
                radio: float | None = Query(None, ge=0, allow_inf_nan=False), producto_id: int | None = None,
                limite: int = Query(10, ge=1, le=100)):
        """Tiendas por distancia en metros. Con producto_id solo aparecen tiendas con stock."""
        with lock:
            return cercanas(estado["motor"], lat, lon, producto_id, radio, limite)

    return router
