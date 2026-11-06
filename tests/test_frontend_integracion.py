"""Pruebas de la adaptación visual sin alterar el resultado SQL original."""

import unittest

from frontend.main import Aplicacion
from frontend.motor import Resultado


class TestFragmentos(unittest.TestCase):
    def test_match_con_columna_visible_agrega_fragmento_sin_mutar_resultado(self):
        resultado = Resultado(columnas=["id", "contenido", "relevancia"],
                              filas=[(1, "texto inicial sobre gatos y perros", 0.75)])
        columnas, filas = Aplicacion._preparar_resultados_texto(
            "SELECT id, contenido, SCORE() AS relevancia FROM docs "
            "WHERE MATCH(contenido, 'gatos') USING BM25", resultado)
        self.assertEqual(columnas[-1], "fragmento")
        self.assertIn("gatos", filas[0][-1])
        self.assertEqual(resultado.columnas, ["id", "contenido", "relevancia"])
        self.assertEqual(len(resultado.filas[0]), 3)

    def test_match_sin_columna_visible_no_inventa_texto(self):
        resultado = Resultado(columnas=["id"], filas=[(1,)])
        columnas, filas = Aplicacion._preparar_resultados_texto(
            "SELECT id FROM docs WHERE MATCH(contenido, 'gatos') USING BM25", resultado)
        self.assertEqual((columnas, filas), (resultado.columnas, resultado.filas))

    def test_consulta_sin_match_no_cambia_resultado(self):
        resultado = Resultado(columnas=["id"], filas=[(1,)])
        self.assertEqual(Aplicacion._preparar_resultados_texto("SELECT id FROM docs", resultado),
                         (resultado.columnas, resultado.filas))
