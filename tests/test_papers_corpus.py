"""Corpus de papers para RAG (issue #97): arXiv, fragmentación, CSV/COPY y SPIMI.

No usa la red: la API de arXiv se reemplaza por respuestas fijas.
"""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag import arxiv, corpus
from rag.chunking import extraer_paginas, fragmentar, limpiar, quitar_referencias

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1603.09320v4</id>
    <published>2016-03-30T11:18:14Z</published>
    <title>Efficient and robust approximate nearest neighbor search
      using Hierarchical Navigable Small World graphs</title>
    <summary>  We present a new approach for the approximate K-nearest neighbor search.
    </summary>
    <author><name>Yu. A. Malkov</name></author>
    <author><name>D. A. Yashunin</name></author>
    <link href="http://arxiv.org/pdf/1603.09320v4" rel="related" type="application/pdf" title="pdf"/>
    <arxiv:primary_category term="cs.DS"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/cs/0101001v1</id>
    <published>2001-01-02T00:00:00Z</published>
    <title>An old style identifier</title>
    <summary>Abstract.</summary>
    <author><name>A. Author</name></author>
    <arxiv:primary_category term="cs.DB"/>
  </entry>
</feed>"""

ERROR_FEED = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/api/errors#incorrect_id_format_for_bad</id><title>Error</title></entry></feed>"""

OAI = b"""<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><GetRecord><record><metadata>
<arXiv xmlns="http://arxiv.org/OAI/arXiv/"><license>http://creativecommons.org/licenses/by/4.0/</license></arXiv>
</metadata></record></GetRecord></OAI-PMH>"""


def pdf_con_texto(paginas):
    """PDF mínimo válido (Helvetica, una línea por página) sin dependencias externas."""
    objetos = ["<< /Type /Catalog /Pages 2 0 R >>", None,
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for texto in paginas:
        contenido = f"BT /F1 10 Tf 20 700 Td ({texto}) Tj ET".encode("latin-1")
        objetos.append(f"<< /Length {len(contenido)} >>\nstream\n{contenido.decode('latin-1')}\nendstream")
        objetos.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objetos)} 0 R >>")
        kids.append(f"{len(objetos)} 0 R")
    objetos[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    salida, offsets = b"%PDF-1.4\n", []
    for numero, cuerpo in enumerate(objetos, 1):
        offsets.append(len(salida))
        salida += f"{numero} 0 obj\n{cuerpo}\nendobj\n".encode("latin-1")
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    salida += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return salida


def oraciones(n, palabra="vector"):
    """n palabras en oraciones de 10 palabras."""
    palabras = [f"{palabra}{i}" for i in range(n)]
    return " ".join(p + ("." if (i + 1) % 10 == 0 else "") for i, p in enumerate(palabras))


class ClienteFalso:
    def __init__(self, respuestas):
        self.respuestas, self.urls = respuestas, []

    def get(self, url, params=None):
        self.urls.append((url, params))
        return self.respuestas(url, params)


class TestArxiv(unittest.TestCase):
    def test_parse_feed_extrae_metadata_y_version(self):
        filas = arxiv.parse_feed(FEED, "ann_grafos")
        self.assertEqual([f["arxiv_id"] for f in filas], ["1603.09320", "cs/0101001"])
        hnsw = filas[0]
        self.assertEqual(hnsw["version"], "v4")
        self.assertEqual(hnsw["anio"], "2016")
        self.assertEqual(hnsw["categoria"], "cs.DS")
        self.assertEqual(hnsw["autores"], "Yu. A. Malkov; D. A. Yashunin")
        self.assertTrue(hnsw["titulo"].startswith("Efficient and robust") and "\n" not in hnsw["titulo"])
        self.assertEqual(hnsw["url_pdf"], "https://arxiv.org/pdf/1603.09320v4")
        self.assertEqual(filas[1]["url_pdf"], "https://arxiv.org/pdf/cs/0101001v1")
        self.assertEqual(arxiv.nombre_pdf("cs/0101001"), "cs_0101001.pdf")
        self.assertEqual(arxiv.parse_feed(ERROR_FEED), [])

    def test_licencia_oai_y_por_defecto(self):
        self.assertEqual(arxiv.parse_licencia(OAI), "http://creativecommons.org/licenses/by/4.0/")
        self.assertEqual(arxiv.parse_licencia(b"<OAI-PMH/>"), arxiv.LICENCIA_POR_DEFECTO)

    def test_seleccion_deduplica_respeta_maximo_y_escribe_csv(self):
        solo_hnsw = FEED[:FEED.index(b"  <entry>\n    <id>http://arxiv.org/abs/cs/")] + b"</feed>"

        def respuestas(url, params):
            if url == arxiv.OAI_URL:
                return OAI
            return solo_hnsw if "id_list" in params else FEED
        cliente = ClienteFalso(respuestas)
        temas = (("a", "abs:x", "cat:cs.DB", 5), ("b", "abs:y", "cat:cs.IR", 5))
        filas = arxiv.seleccionar(cliente, maximo=10, temas=temas, semillas=("1603.09320",), log=lambda _: None)
        self.assertEqual([f["arxiv_id"] for f in filas], ["1603.09320", "cs/0101001"])
        self.assertEqual(filas[0]["tema"], "semilla")
        self.assertEqual(filas[1]["tema"], "a")  # round-robin: el primer tema gana el duplicado
        self.assertTrue(all(f["licencia"].endswith("by/4.0/") for f in filas))
        self.assertEqual(len(arxiv.seleccionar(cliente, maximo=1, temas=temas, semillas=(), licencias=False,
                                               log=lambda _: None)), 1)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "seleccion.csv"
            arxiv.escribir_seleccion(filas, path)
            self.assertEqual(arxiv.leer_seleccion(path), filas)
            path.write_text("x\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                arxiv.leer_seleccion(path)

    def test_descarga_omite_existentes_y_rechaza_no_pdf(self):
        filas = arxiv.parse_feed(FEED)
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "1603.09320.pdf").write_bytes(b"%PDF-1.4 existente")
            cliente = ClienteFalso(lambda url, params: b"<html>captcha</html>")
            resultado = arxiv.descargar(cliente, filas, temp, log=lambda _: None)
            self.assertEqual(resultado, {"nuevos": 0, "fallidos": 1, "total": 2})
            self.assertEqual(len(cliente.urls), 1)  # el existente no se pide
            cliente = ClienteFalso(lambda url, params: b"%PDF-1.4 nuevo")
            self.assertEqual(arxiv.descargar(cliente, filas, temp, log=lambda _: None)["nuevos"], 1)
            self.assertTrue((Path(temp) / "cs_0101001.pdf").is_file())


class TestFragmentacion(unittest.TestCase):
    def test_tamanios_entre_minimo_y_maximo(self):
        for total in (200, 351, 499, 500, 501, 650, 899, 1234, 5000):
            with self.subTest(total=total):
                fragmentos = fragmentar([(1, oraciones(total))])
                self.assertEqual(sum(f["palabras"] for f in fragmentos), total)
                self.assertTrue(all(200 <= f["palabras"] <= 500 for f in fragmentos),
                                [f["palabras"] for f in fragmentos])
                self.assertEqual([f["orden"] for f in fragmentos], list(range(1, len(fragmentos) + 1)))

    def test_sin_puntos_corta_en_el_maximo(self):
        fragmentos = fragmentar([(1, " ".join(["word"] * 1100))])
        self.assertEqual([f["palabras"] for f in fragmentos], [500, 300, 300])

    def test_documento_corto_queda_en_un_fragmento(self):
        self.assertEqual([f["palabras"] for f in fragmentar([(1, "solo diez palabras " * 3)])], [9])
        self.assertEqual(fragmentar([(1, "   "), (2, "")]), [])

    def test_conserva_paginas(self):
        paginas = [(1, oraciones(300, "a")), (2, oraciones(300, "b")), (3, oraciones(300, "c"))]
        fragmentos = fragmentar(paginas)
        self.assertEqual(fragmentos[0]["pagina"], 1)
        self.assertEqual(fragmentos[-1]["pagina_fin"], 3)
        for fragmento in fragmentos:
            primera, ultima = fragmento["texto"].split()[0][0], fragmento["texto"].split()[-1][0]
            self.assertEqual("abc".index(primera) + 1, fragmento["pagina"])
            self.assertEqual("abc".index(ultima) + 1, fragmento["pagina_fin"])

    def test_limpieza_y_referencias(self):
        self.assertEqual(limpiar("eﬃcient retrie-\nval\x00 state-of-the-art"), "efficient retrieval  state-of-the-art")
        paginas = [(1, "Intro"), (2, "Body"), (3, "Conclusion\nReferences\n[1] Malkov"), (4, "[2] Jegou")]
        self.assertEqual(quitar_referencias(paginas), [(1, "Intro"), (2, "Body"), (3, "Conclusion")])
        # Un "References" temprano (p. ej. en el índice) no corta el documento.
        temprano = [(1, "References"), (2, "a"), (3, "b")]
        self.assertEqual(quitar_referencias(temprano), temprano)

    def test_extraccion_real_con_pypdf(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "p.pdf"
            path.write_bytes(pdf_con_texto(["Hierarchical navigable small world", "Inverted file index"]))
            paginas = extraer_paginas(path)
        self.assertEqual([n for n, _ in paginas], [1, 2])
        self.assertIn("navigable", paginas[0][1])
        self.assertIn("Inverted", paginas[1][1])


class TestCorpusEnMotor(unittest.TestCase):
    def preparar(self, root):
        filas = arxiv.parse_feed(FEED)
        for fila in filas:
            fila["licencia"] = arxiv.LICENCIA_POR_DEFECTO
        arxiv.escribir_seleccion(filas, root / "seleccion.csv")
        (root / "pdf").mkdir()
        (root / "pdf/1603.09320.pdf").write_bytes(pdf_con_texto(["x"]))  # el segundo falta
        curso = root / "curso"
        curso.mkdir()
        (curso / "ppt09.pdf").write_bytes(pdf_con_texto(["x"]))
        with (curso / "curso.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(corpus.CAMPOS_CURSO)
            writer.writerow(["ppt09.pdf", "PPT 09: índice invertido, \"SPIMI\"", "Profesor", "2026",
                             "curso", "Material de clase, uso interno"])

    @staticmethod
    def extraer_falso(pdf):
        if pdf.name == "ppt09.pdf":
            return [(1, oraciones(250, "spimi") + " BM25 inverted index posting lists.")]
        return [(1, oraciones(400, "graph") + " hierarchical navigable small world."),
                (2, oraciones(400, "layer")), (3, "References\n[1] noise noise")]

    def test_construir_y_cargar_en_el_motor(self):
        with tempfile.TemporaryDirectory(prefix="papers's-") as temp:
            root = Path(temp)
            self.preparar(root)
            meta = corpus.construir(root / "seleccion.csv", root / "pdf", root / "curso", root / "out",
                                    extraer=self.extraer_falso, log=lambda _: None)
            self.assertEqual(meta["papers"], 2)
            self.assertEqual(meta["pdf_faltantes"], ["cs/0101001"])
            self.assertLessEqual(meta["palabras"]["max"], 500)
            self.assertEqual(meta["palabras"]["bajo_minimo"], 0)
            self.assertEqual(json.loads((root / "out/metadata.json").read_text("utf-8")), meta)
            with (root / "out/fragmentos.csv").open(encoding="utf-8", newline="") as stream:
                fragmentos = list(csv.DictReader(stream))
            self.assertNotIn("noise", " ".join(f["texto"] for f in fragmentos))
            with self.assertRaises(FileExistsError):
                corpus.construir(root / "seleccion.csv", root / "pdf", root / "curso", root / "out",
                                 extraer=self.extraer_falso, log=lambda _: None)

            resultado = corpus.cargar(root / "out", root / "db")
            self.assertEqual(resultado["fragmentos"], len(fragmentos))
            from frontend.motor import Motor
            motor = Motor(directorio=str(root / "db"), modo_demo=False)
            try:
                r = motor.ejecutar("SELECT f.paper_id, f.pagina, SCORE() AS s FROM fragmentos f "
                                   "WHERE MATCH(texto, 'hierarchical navigable graphs') USING BM25 "
                                   "ORDER BY s DESC LIMIT 3")
                self.assertFalse(r.tiene_error, r.error)
                self.assertEqual(r.filas[0][0], 1)  # el fragmento viene del paper HNSW
                self.assertIn(r.filas[0][1], (1, 2))
                r = motor.ejecutar("SELECT titulo, fuente, anio FROM papers WHERE id = 2")
                self.assertEqual(list(r.filas[0]), ['PPT 09: índice invertido, "SPIMI"', "curso", 2026])
                r = motor.ejecutar("INSERT INTO fragmentos VALUES (999, 77, 1, 1, 1, 1, 'x')")
                self.assertTrue(r.tiene_error)  # paper 77 no existe: llave foránea
            finally:
                motor.cerrar()
            with self.assertRaises(ValueError):
                corpus.cargar(root / "out", root / "db")

    def test_sql_usa_rutas_relativas_al_repo(self):
        # Fuera del repo la ruta queda absoluta; se compara con resolve() para
        # que funcione igual en Linux (/tmp/...) y en Windows (C:\\...).
        afuera = Path(tempfile.gettempdir()) / "o'k" / "f.csv"
        sql = corpus.load_sql(corpus.ROOT / "datasets/papers/generated/papers.csv", afuera)
        self.assertIn("COPY papers FROM 'datasets/papers/generated/papers.csv'", sql)
        esperado = str(afuera.resolve()).replace("'", "''")
        self.assertIn(f"COPY fragmentos FROM '{esperado}'", sql)
        self.assertIn("USING SPIMI WITH (LANGUAGE = 'en')", sql)

    def test_sin_pdfs_es_error_claro(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            arxiv.escribir_seleccion(arxiv.parse_feed(FEED), root / "seleccion.csv")
            with patch.object(corpus, "extraer_paginas"), self.assertRaises(ValueError):
                corpus.construir(root / "seleccion.csv", root / "pdf", root / "nada", root / "out",
                                 log=lambda _: None)


if __name__ == "__main__":
    unittest.main()
