"""API de catálogo, recomendaciones y tiendas."""
import math
from typing import Literal
from tienda.indice_imagen import ImageIndex

from fastapi import APIRouter, HTTPException, Query

from tienda.recomendaciones import (CANDIDATOS, cercanas, compras, consultar, fusionar, literal,
                                    misma_categoria, texto, visual)

# Pesos medidos en benchmarks/tienda con dos métricas (tipo de producto y co-compras
# posteriores), elegidos en validación y reportados en prueba con fusión RRF.
PESOS = "1,0.5,1"
PESO_CATEGORIA = 0.25


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
            filtros.append(f"categoria = {literal(categoria)}")
        if precio_min is not None and precio_max is not None and precio_min > precio_max:
            raise HTTPException(422, "Rango de precios invertido")
        for operador, valor in ((">=", precio_min), ("<=", precio_max)):
            if valor is not None:
                filtros.append(f"precio {operador} {valor:.12f}")
        if q:
            filtros.append(f"MATCH(descripcion, {literal(q)}) USING BM25")
        where = " WHERE " + " AND ".join(filtros) if filtros else ""
        orden = "SCORE() DESC, id" if q else "id"
        with lock:
            return consultar(estado["motor"], f"SELECT * FROM productos{where} "
                             f"ORDER BY {orden} LIMIT {limite} OFFSET {offset}")

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
                        fusion: Literal["rrf", "max"] = "rrf"):
        try:
            valores = [float(p) for p in pesos.split(",")]
        except ValueError:
            valores = []
        if (len(valores) != 3 or any(p < 0 for p in valores)
                or not math.isfinite(sum(valores)) or sum(valores) <= 0):
            raise HTTPException(422, "Indique tres pesos no negativos con suma positiva y finita")
        usar_mobilenet = vector_imagen != "sift"
        with lock:
            motor = estado["motor"]
            origen = producto(motor, id)
            catalogo_imagenes = consultar(motor, "SELECT id, imagen FROM productos") if usar_mobilenet else None
        if usar_mobilenet:
            # Fuera del lock del motor: extraer el catálogo tarda minutos la primera vez y
            # no debe congelar el resto de la API. El índice tiene su propio lock.
            indice = estado.setdefault("indice_mobilenet", ImageIndex(estado["motor"].directorio))
            try:
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
            senales = {"compras": compras(motor, id), "imagen": imagen,
                       "texto": texto(motor, origen["descripcion"])}
            pesos_senales = dict(zip(senales, valores))
            if peso_categoria > 0:
                # Solo los candidatos de señales con peso: una señal apagada no aporta productos.
                candidatos = {i for nombre, puntos in senales.items() if pesos_senales[nombre] > 0
                              for i, valor in puntos.items() if valor > 0} - {id}
                senales["categoria"] = misma_categoria(motor, origen.get("categoria"), candidatos)
                pesos_senales["categoria"] = peso_categoria
            filas = fusionar(id, senales, pesos_senales, fusion)
            return [{**producto(motor, fila["id"]), **fila} for fila in filas]

    @router.get("/tiendas/cercanas")
    def tiendas(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
                radio: float | None = Query(None, ge=0, allow_inf_nan=False), producto_id: int | None = None,
                limite: int = Query(10, ge=1, le=100)):
        """Tiendas por distancia en metros. Con producto_id solo aparecen tiendas con stock."""
        with lock:
            return cercanas(estado["motor"], lat, lon, producto_id, radio, limite)

    return router
