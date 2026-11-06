import unittest

from frontend.panel_resultados import abreviar


class TestAbreviarCelda(unittest.TestCase):
    def test_texto_que_cabe_no_cambia(self):
        self.assertEqual(abreviar("gatos", 5, len), "gatos")

    def test_usa_elipsis_sin_cortar_el_valor_original(self):
        original = "documento largo"
        self.assertEqual(abreviar(original, 6, len), "docum…")
        self.assertEqual(original, "documento largo")
        self.assertEqual(abreviar(original, 1, len), "…")
        self.assertEqual(abreviar(original, 0, len), "")

    def test_respeta_ancho_variable_de_caracteres(self):
        medir = lambda texto: sum(3 if caracter == "W" else 1 for caracter in texto)
        self.assertEqual(abreviar("WWaa", 5, medir), "W…")
