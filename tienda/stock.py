"""Stock sintético y reproducible para las tiendas reales del issue #100."""

import argparse
import random

from tienda.amazon import PRODUCTOS
from tienda.comun import DATASET_DIR, GENERATED_DIR, escribir_csv, leer_csv
from tienda.imagenes import CAMPOS_PRODUCTOS
from tienda.osm import CAMPOS_TIENDAS

TIENDAS = DATASET_DIR / "tiendas_lima.csv"
STOCK = GENERATED_DIR / "stock.csv"
CAMPOS_STOCK = ("id", "tienda_id", "producto_id", "unidades")
SEMILLA = 100


def generar(productos, tiendas, semilla=SEMILLA):
    """Asigna cada producto a 1–3 tiendas; el orden del CSV no cambia el resultado."""
    productos_ids = sorted(int(fila["id"]) for fila in productos)
    tiendas_ids = sorted(int(fila["id"]) for fila in tiendas)
    if not productos_ids or not tiendas_ids:
        raise ValueError("Se necesitan productos y tiendas para generar stock")
    if len(set(productos_ids)) != len(productos_ids) or len(set(tiendas_ids)) != len(tiendas_ids):
        raise ValueError("Los identificadores de productos y tiendas deben ser únicos")
    if productos_ids[0] < 1 or tiendas_ids[0] < 1:
        raise ValueError("Los identificadores deben ser positivos")
    filas = []
    for producto_id in productos_ids:
        rng = random.Random(f"{semilla}:{producto_id}")
        cantidad = rng.randint(1, min(3, len(tiendas_ids)))
        for tienda_id in sorted(rng.sample(tiendas_ids, cantidad)):
            filas.append({"id": len(filas) + 1, "tienda_id": tienda_id,
                          "producto_id": producto_id, "unidades": rng.randint(1, 20)})
    return filas


def main(argv=None):
    parser = argparse.ArgumentParser(description="Genera stock reproducible para la tienda")
    parser.add_argument("--semilla", type=int, default=SEMILLA)
    args = parser.parse_args(argv)
    productos = leer_csv(PRODUCTOS, CAMPOS_PRODUCTOS)
    tiendas = leer_csv(TIENDAS, CAMPOS_TIENDAS)
    filas = generar(productos, tiendas, args.semilla)
    escribir_csv(STOCK, CAMPOS_STOCK, filas)
    print(f"{len(filas)} filas de stock en {STOCK} (semilla {args.semilla})")


if __name__ == "__main__":
    main()
