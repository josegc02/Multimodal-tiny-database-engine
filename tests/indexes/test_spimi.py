import os
import shutil
import tempfile
import unittest

from engine.indexes.spimi import HEADER, PAGE_SIZE, POSTING, SpimiIndex, decode_postings, encode_postings, pages_for


class SpimiTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "noticias.spimi")


class TestPostings(SpimiTestCase):
    def test_ida_y_vuelta(self):
        postings = [(1, 1), (2, 1), (3, 2), (4_000_000_000, 70_000)]
        data = encode_postings(postings)
        self.assertEqual(len(data), len(postings) * POSTING.size)
        self.assertEqual(decode_postings(data), postings)

    def test_lista_vacia(self):
        self.assertEqual(encode_postings([]), b"")
        self.assertEqual(decode_postings(b""), [])

    def test_paginas_necesarias(self):
        for size, esperado in ((0, 0), (1, 1), (PAGE_SIZE, 1), (PAGE_SIZE + 1, 2), (3 * PAGE_SIZE, 3)):
            with self.subTest(size=size):
                self.assertEqual(pages_for(size), esperado)


class TestArchivo(SpimiTestCase):
    def test_indice_nuevo_solo_tiene_la_cabecera(self):
        with SpimiIndex(self.path) as index:
            self.assertEqual(len(index), 0)
            self.assertEqual(index.language, "es")
            self.assertEqual(index.page_count, 1)
        self.assertEqual(os.path.getsize(self.path), PAGE_SIZE)
        self.assertLessEqual(HEADER.size, PAGE_SIZE)

    def test_cabecera_persiste_al_reabrir(self):
        with SpimiIndex(self.path, "en") as index:
            index.doc_count, index.next_doc_id, index.term_count = 3, 5, 7
            index.total_length = 2 ** 40
            index.postings_start, index.postings_pages = 2, 4
            index.documents_start, index.documents_pages = 6, 1
        with SpimiIndex(self.path) as index:
            self.assertEqual(len(index), 3)
            self.assertEqual((index.next_doc_id, index.term_count, index.total_length), (5, 7, 2 ** 40))
            self.assertEqual(index.language, "en")
            self.assertEqual((index.postings_start, index.postings_pages), (2, 4))
            self.assertEqual((index.documents_start, index.documents_pages), (6, 1))

    def test_paginas_seguidas(self):
        data = encode_postings((i, 1) for i in range(1000))
        with SpimiIndex(self.path) as index:
            ocupadas = index._write_pages(1, data)
            self.assertEqual(ocupadas, 2)
            self.assertEqual(index.page_count, 3)
        self.assertEqual(os.path.getsize(self.path), 3 * PAGE_SIZE)
        with SpimiIndex(self.path) as index:
            leido = index._read_pages(1, ocupadas)
        self.assertEqual(decode_postings(leido[:len(data)]), [(i, 1) for i in range(1000)])

    def test_idioma_debe_coincidir_con_el_archivo(self):
        SpimiIndex(self.path, "en").close()
        with self.assertRaises(ValueError):
            SpimiIndex(self.path, "es")
        os.remove(self.path)  # en Windows falla si el archivo quedó abierto

    def test_idioma_no_soportado(self):
        with self.assertRaises(ValueError):
            SpimiIndex(self.path, "fr")
        self.assertFalse(os.path.exists(self.path))

    def test_rechaza_otro_tipo_de_archivo(self):
        with open(self.path, "wb") as f:
            f.write(b"esto no es un indice" * 100)
        with self.assertRaises(ValueError):
            SpimiIndex(self.path)
        os.remove(self.path)

    def test_cerrar_dos_veces_no_falla(self):
        index = SpimiIndex(self.path)
        index.close()
        index.close()


if __name__ == "__main__":
    unittest.main()
