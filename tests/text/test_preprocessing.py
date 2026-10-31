import unittest

from engine.text.preprocessing import quitar_stopwords, quitar_tildes, stemizar, stopwords, tokenizar


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


class TestStopwords(unittest.TestCase):
    def filtrar(self, texto, idioma="es"):
        return quitar_stopwords(tokenizar(texto), idioma)

    def test_quita_palabras_funcionales(self):
        self.assertEqual(self.filtrar("La casa es grande"), ["casa", "grande"])
        self.assertEqual(self.filtrar("The house is on the hill", "en"), ["house", "hill"])

    def test_conserva_palabras_con_contenido(self):
        self.assertEqual(self.filtrar("el valor del trabajo"), ["valor", "trabajo"])
        for palabra in ("trabajo", "tiempo", "valor", "parte", "estados", "lugar", "nuevo", "mejor", "verdad", "tres"):
            with self.subTest(palabra=palabra):
                self.assertNotIn(palabra, stopwords("es"))

    def test_compara_sin_tildes_pero_conserva_el_token(self):
        self.assertEqual(self.filtrar("MÁS mas está esta"), [])
        self.assertEqual(self.filtrar("la canción"), ["canción"])

    def test_cada_idioma_usa_su_lista(self):
        self.assertEqual(self.filtrar("the casa"), ["the", "casa"])
        self.assertEqual(self.filtrar("the casa", "en"), ["casa"])
        self.assertEqual(self.filtrar("I don't know", "en"), ["know"])

    def test_consulta_de_solo_stopwords_queda_vacia(self):
        self.assertEqual(self.filtrar("de la"), [])

    def test_idioma_no_soportado(self):
        with self.assertRaises(ValueError):
            quitar_stopwords(["casa"], "fr")

    def test_quitar_tildes_conserva_la_enie(self):
        self.assertEqual(quitar_tildes("canción"), "cancion")
        self.assertEqual(quitar_tildes("pingüino"), "pinguino")
        self.assertEqual(quitar_tildes("año"), "año")


class TestStemizar(unittest.TestCase):
    def test_variantes_comparten_raiz(self):
        grupos = (("corriendo", "corrió", "corrieron", "correr"), ("casa", "casas"), ("niño", "niña"),
                  ("canción", "canciones"), ("computadora", "computadoras", "computación"))
        for grupo in grupos:
            with self.subTest(grupo=grupo):
                self.assertEqual(len(set(stemizar(list(grupo)))), 1)

    def test_el_resultado_no_tiene_tildes(self):
        self.assertEqual(stemizar(["canción", "pingüino", "árboles"]), ["cancion", "pinguin", "arbol"])
        self.assertEqual(stemizar(["café"], "en"), ["cafe"])

    def test_conserva_la_enie(self):
        self.assertEqual(stemizar(["niño", "caña"]), ["niñ", "cañ"])

    def test_no_altera_numeros_ni_siglas(self):
        self.assertEqual(stemizar(["2024", "3.14", "mp3", "onu"]), ["2024", "3.14", "mp3", "onu"])

    def test_usa_el_stemmer_del_idioma(self):
        self.assertEqual(stemizar(["running", "runs"], "en"), ["run", "run"])

    def test_idioma_no_soportado(self):
        with self.assertRaises(ValueError):
            stemizar(["casa"], "fr")


if __name__ == "__main__":
    unittest.main()
