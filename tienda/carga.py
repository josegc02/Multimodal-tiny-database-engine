"""Prepara y carga el catálogo de la tienda en el motor (issue #100).

Primero ejecute tienda.amazon seleccionar, tienda.imagenes y tienda.amazon compras.
Luego: python -m tienda.carga preparar; python -m tienda.carga cargar --datos data/app
"""

import argparse
import hashlib
import json
from pathlib import Path

from tienda.amazon import CAMPOS_COMPRAS, COMPRAS, PRODUCTOS
from tienda.comun import DATASET_DIR, GENERATED_DIR, ROOT, escribir_csv, leer_csv
from tienda.imagenes import CAMPOS_PRODUCTOS
from tienda.osm import CAMPOS_TIENDAS
from tienda.stock import CAMPOS_STOCK, SEMILLA, STOCK, generar

TIENDAS = DATASET_DIR / "tiendas_lima.csv"
SQL = GENERATED_DIR / "cargar_motor.sql"
METADATA = GENERATED_DIR / "metadata.json"
TABLAS = ("productos", "tiendas", "compras", "stock")


def _literal(valor):
    return "'" + str(valor).replace("'", "''") + "'"


def _ruta_sql(path):
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def load_sql(productos=PRODUCTOS, compras=COMPRAS, tiendas=TIENDAS, stock=STOCK):
    """DDL, COPY e índices; las claves primarias INT ya crean un Hash implícito."""
    return (
        "CREATE TABLE productos (id INT PRIMARY KEY, asin VARCHAR(20), titulo TEXT, "
        "descripcion TEXT, precio FLOAT, rating FLOAT, num_resenas INT, marca TEXT, "
        "categoria TEXT, url_imagen TEXT, imagen IMAGE);\n"
        "CREATE TABLE tiendas (id INT PRIMARY KEY, osm_id VARCHAR(32), nombre TEXT, "
        "tipo VARCHAR(24), distrito TEXT, direccion TEXT, ubicacion POINT);\n"
        "CREATE TABLE compras (id INT PRIMARY KEY, usuario VARCHAR(128), "
        "producto_id INT REFERENCES productos(id), rating FLOAT, fecha INT);\n"
        "CREATE TABLE stock (id INT PRIMARY KEY, tienda_id INT REFERENCES tiendas(id), "
        "producto_id INT REFERENCES productos(id), unidades INT);\n"
        f"COPY productos FROM {_literal(_ruta_sql(productos))} WITH (FORMAT CSV, HEADER TRUE);\n"
        f"COPY tiendas FROM {_literal(_ruta_sql(tiendas))} WITH (FORMAT CSV, HEADER TRUE);\n"
        f"COPY compras FROM {_literal(_ruta_sql(compras))} WITH (FORMAT CSV, HEADER TRUE);\n"
        f"COPY stock FROM {_literal(_ruta_sql(stock))} WITH (FORMAT CSV, HEADER TRUE);\n"
        "CREATE INDEX productos_precio ON productos (precio) USING BTREE;\n"
        "CREATE INDEX productos_descripcion ON productos (descripcion) USING SPIMI WITH (LANGUAGE = 'en');\n"
        "CREATE INDEX productos_imagen ON productos (imagen) USING HNSW WITH (METRIC = cosine);\n"
        "CREATE INDEX tiendas_ubicacion ON tiendas (ubicacion) USING RTREE;\n"
        "CREATE INDEX compras_usuario ON compras (usuario) USING HASH;\n"
    )


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def preparar(productos=PRODUCTOS, compras=COMPRAS, tiendas=TIENDAS,
             stock=STOCK, sql=SQL, metadata=METADATA, semilla=SEMILLA,
             minimo_productos=5000, maximo_productos=10000):
    productos_filas = leer_csv(productos, CAMPOS_PRODUCTOS)
    compras_filas = leer_csv(compras, CAMPOS_COMPRAS)
    tiendas_filas = leer_csv(tiendas, CAMPOS_TIENDAS)
    if not minimo_productos <= len(productos_filas) <= maximo_productos:
        raise ValueError(f"Se esperaban {minimo_productos}–{maximo_productos} productos con imagen; "
                         f"hay {len(productos_filas)}")
    if not tiendas_filas:
        raise ValueError("No hay tiendas para generar stock")
    producto_ids = {int(fila["id"]) for fila in productos_filas}
    if len(producto_ids) != len(productos_filas):
        raise ValueError("Hay identificadores de producto repetidos")
    for fila in compras_filas:
        if int(fila["producto_id"]) not in producto_ids:
            raise ValueError(f"La compra {fila['id']} referencia un producto ausente")
    stock_filas = generar(productos_filas, tiendas_filas, semilla)
    escribir_csv(stock, CAMPOS_STOCK, stock_filas)
    sql = Path(sql)
    sql.parent.mkdir(parents=True, exist_ok=True)
    sql.write_text(load_sql(productos, compras, tiendas, stock), encoding="utf-8")
    info = {"semilla_stock": semilla,
            "filas": {"productos": len(productos_filas), "compras": len(compras_filas),
                      "tiendas": len(tiendas_filas), "stock": len(stock_filas)},
            "sha256": {Path(path).name: _digest(path)
                       for path in (productos, compras, tiendas, stock)}}
    metadata = Path(metadata)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return info


def cargar(sql=SQL, datos=ROOT / "data" / "app"):
    from frontend.motor import Motor

    sentencias = [linea.strip() for linea in Path(sql).read_text(encoding="utf-8").splitlines()
                  if linea.strip()]
    motor = Motor(directorio=str(datos), modo_demo=False)
    try:
        presentes = set(TABLAS) & set(motor.catalog.tables)
        if presentes:
            raise ValueError(f"{datos} ya contiene tablas de la tienda: {', '.join(sorted(presentes))}; "
                             "use otra carpeta de datos")
        for sentencia in sentencias:
            resultado = motor.ejecutar(sentencia)
            if resultado.tiene_error:
                raise ValueError(f"Falló {sentencia[:100]}: {resultado.error}")
        return {tabla: motor.ejecutar(f"SELECT COUNT(*) FROM {tabla}").filas[0][0]
                for tabla in TABLAS}
    finally:
        motor.cerrar()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepara y carga datos de la tienda (issue #100)")
    sub = parser.add_subparsers(dest="comando", required=True)
    prep = sub.add_parser("preparar", help="genera stock, SQL de carga y hashes")
    prep.add_argument("--semilla", type=int, default=SEMILLA)
    car = sub.add_parser("cargar", help="carga las cuatro tablas e índices en el motor")
    car.add_argument("--datos", type=Path, default=ROOT / "data" / "app")
    args = parser.parse_args(argv)
    resultado = preparar(semilla=args.semilla) if args.comando == "preparar" else cargar(datos=args.datos)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
