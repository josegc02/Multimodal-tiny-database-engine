"""El esquema de la tienda debe cargar datos reproducibles y consultables."""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from tienda import carga
from tienda.amazon import CAMPOS_COMPRAS
from tienda.comun import escribir_csv
from tienda.imagenes import CAMPOS_PRODUCTOS
from tienda.osm import CAMPOS_TIENDAS
from tienda.stock import generar


class TestTiendaCarga(unittest.TestCase):
    def test_stock_es_estable_y_todos_los_productos_tienen_stock(self):
        productos = [{"id": "2"}, {"id": "1"}, {"id": "3"}]
        tiendas = [{"id": "20"}, {"id": "10"}, {"id": "30"}]
        primero = generar(productos, tiendas, semilla=42)
        self.assertEqual(primero, generar(list(reversed(productos)), list(reversed(tiendas)), 42))
        self.assertNotEqual(primero, generar(productos, tiendas, 43))
        self.assertEqual({fila["producto_id"] for fila in primero}, {1, 2, 3})
        self.assertEqual(len({(fila["producto_id"], fila["tienda_id"]) for fila in primero}), len(primero))
        with self.assertRaises(ValueError):
            generar(productos, [{"id": "10"}, {"id": "10"}])

    def test_preparar_y_cargar_en_motor_persistente(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generado = root / "generated"
            productos = generado / "productos.csv"
            compras = generado / "compras.csv"
            tiendas = root / "tiendas_lima.csv"
            stock = generado / "stock.csv"
            sql = generado / "cargar_motor.sql"
            metadata = generado / "metadata.json"
            filas_productos = [
                {"id": i, "asin": f"A{i}", "titulo": f"Juego {i}",
                 "descripcion": f"video game console controller adventure game {i}",
                 "precio": i * 10.0, "rating": 4.0, "num_resenas": 10,
                 "marca": "Marca", "categoria": "Video Games", "url_imagen": "https://example.org/a.jpg",
                 "imagen": str(root / f"{i}.jpg")}
                for i in (1, 2)
            ]
            escribir_csv(productos, CAMPOS_PRODUCTOS, filas_productos)
            escribir_csv(compras, CAMPOS_COMPRAS, [
                {"id": 1, "usuario": "u1", "producto_id": 1, "rating": 5, "fecha": 1700000000},
                {"id": 2, "usuario": "u1", "producto_id": 2, "rating": 4, "fecha": 1700000001},
            ])
            escribir_csv(tiendas, CAMPOS_TIENDAS, [
                {"id": 1, "osm_id": "node/1", "nombre": "Tienda A", "tipo": "video_games",
                 "distrito": "Lima", "direccion": "Calle 1", "ubicacion": "POINT(-12.05, -77.03)"},
                {"id": 2, "osm_id": "node/2", "nombre": "Tienda B", "tipo": "electronics",
                 "distrito": "Lima", "direccion": "Calle 2", "ubicacion": "POINT(-12.06, -77.04)"},
            ])
            info = carga.preparar(productos, compras, tiendas, stock, sql, metadata,
                                  semilla=42, minimo_productos=2, maximo_productos=2)
            self.assertEqual(info["filas"]["productos"], 2)
            self.assertEqual(json.loads(metadata.read_text(encoding="utf-8")), info)
            with stock.open(encoding="utf-8", newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), info["filas"]["stock"])
            self.assertIn("USING HNSW WITH (METRIC = cosine)", sql.read_text(encoding="utf-8"))

            with patch("engine.storage.media_store.extract_features",
                       side_effect=lambda kind, path: np.array([1.0, float(Path(path).stem), 0.0])):
                conteos = carga.cargar(sql, root / "db")
            self.assertEqual(conteos, info["filas"])
            from frontend.motor import Motor
            motor = Motor(directorio=str(root / "db"), modo_demo=False)
            try:
                self.assertEqual(motor.ejecutar("SELECT COUNT(*) FROM compras").filas, [(2,)])
                self.assertEqual(set(motor.catalog.table("productos").indexes),
                                 {"id", "precio", "descripcion", "imagen"})
                self.assertEqual(set(motor.catalog.table("tiendas").indexes), {"id", "ubicacion"})
                texto = motor.ejecutar("SELECT id FROM productos WHERE "
                                       "MATCH(descripcion, 'console controller') USING BM25 LIMIT 2")
                self.assertFalse(texto.tiene_error, texto.error)
                self.assertEqual(len(texto.filas), 2)
                cerca = motor.ejecutar("SELECT id FROM tiendas ORDER BY "
                                       "distancia(ubicacion, POINT(-12.05, -77.03)) LIMIT 1")
                self.assertFalse(cerca.tiene_error, cerca.error)
                self.assertEqual(cerca.filas, [(1,)])
            finally:
                motor.cerrar()
            with self.assertRaisesRegex(ValueError, "ya contiene tablas"):
                carga.cargar(sql, root / "db")


if __name__ == "__main__":
    unittest.main()
