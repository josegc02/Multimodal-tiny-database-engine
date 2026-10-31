import unittest

from engine.text.preprocessing import tokenizar


class TestTokenizar(unittest.TestCase):
    def test_frases(self):
        casos = {
            "La casa es grande": ["la", "casa", "es", "grande"],
            "¡Hola, mundo! ¿Cómo estás?": ["hola", "mundo", "cómo", "estás"],
            "bases-de-datos (2026)": ["bases", "de", "datos", "2026"],
            "fin de frase.Otra": ["fin", "de", "frase", "otra"],
            "snake_case": ["snake", "case"],
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(tokenizar(texto), esperado)

    def test_siglas_con_y_sin_puntos_son_el_mismo_token(self):
        for texto in ("ONU", "O.N.U.", "O.N.U", "o.n.u."):
            with self.subTest(texto=texto):
                self.assertEqual(tokenizar(texto), ["onu"])
        self.assertEqual(tokenizar("La O.N.U. aprobó"), ["la", "onu", "aprobó"])

    def test_conserva_numeros(self):
        self.assertEqual(tokenizar("Costó 1500 soles en 2024."), ["costó", "1500", "soles", "en", "2024"])
        self.assertEqual(tokenizar("pi es 3,14 o 3.14"), ["pi", "es", "3.14", "o", "3.14"])
        self.assertEqual(tokenizar("mp3 y 10km"), ["mp3", "y", "10km"])

    def test_tildes_y_enie_llegan_intactas_al_stemmer(self):
        self.assertEqual(tokenizar("CANCIÓN del Año"), ["canción", "del", "año"])
        self.assertEqual(tokenizar("canción"), ["canción"])  # tilde como carácter aparte

    def test_apostrofe_interno(self):
        self.assertEqual(tokenizar("Don't stop"), ["don't", "stop"])
        self.assertEqual(tokenizar("don’t 'hola'"), ["don't", "hola"])

    def test_textos_sin_tokens(self):
        for texto in ("", "   ", "¡¿...?!", "---"):
            with self.subTest(texto=texto):
                self.assertEqual(tokenizar(texto), [])


if __name__ == "__main__":
    unittest.main()
