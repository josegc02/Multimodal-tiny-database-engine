import os
import shutil
import tempfile
import unittest

from engine.indexes.spimi import (BLOCK_ENTRY, HEADER, MAX_TERM_BYTES, PAGE_SIZE, POSTING, SpimiIndex, decode_postings,
                                  encode_postings, pages_for, read_block)


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


class TestBloques(SpimiTestCase):
    def build(self, documents, block_size=10_000):
        with SpimiIndex(self.path, block_size=block_size) as index:
            paths = index._build_blocks(documents)
            self.addCleanup(index._remove_blocks, paths)
            return [dict(read_block(path)) for path in paths], paths, index.next_doc_id

    def test_ejemplo_con_dos_bloques(self):
        # El bloque 1 se llena justo al terminar el segundo documento.
        bloques, _, siguiente = self.build(["casa grande", "casa bonita", "gato grande"], block_size=60)
        self.assertEqual(bloques, [
            {"bonit": [(1, 1)], "cas": [(0, 1), (1, 1)], "grand": [(0, 1)]},
            {"gat": [(2, 1)], "grand": [(2, 1)]},
        ])
        self.assertEqual(siguiente, 3)

    def test_un_bloque_si_todo_cabe(self):
        bloques, _, _ = self.build(["casa grande"] * 50)
        self.assertEqual(len(bloques), 1)

    def test_limite_minimo_da_un_bloque_por_documento(self):
        bloques, _, _ = self.build(["casa", "gato", "perro"], block_size=1)
        self.assertEqual(bloques, [{"cas": [(0, 1)]}, {"gat": [(1, 1)]}, {"perr": [(2, 1)]}])

    def test_terminos_ordenados_dentro_del_bloque(self):
        _, paths, _ = self.build(["zorro ñandú gato árbol casa"])
        terminos = [termino for termino, _ in read_block(paths[0])]
        self.assertEqual(terminos, sorted(terminos))

    def test_postings_ordenadas_entre_bloques(self):
        bloques, _, _ = self.build(["casa gato"] * 20, block_size=30)
        self.assertGreater(len(bloques), 1)
        doc_ids = [doc_id for bloque in bloques for doc_id, _ in bloque["cas"]]
        self.assertEqual(doc_ids, list(range(20)))

    def test_cuenta_el_tf(self):
        bloques, _, _ = self.build(["casa casa casa gato"])
        self.assertEqual(bloques[0], {"cas": [(0, 3)], "gat": [(0, 1)]})

    def test_documento_mayor_que_el_limite_no_se_parte(self):
        documento = " ".join(f"palabra{i}" for i in range(200))
        bloques, _, _ = self.build([documento, "casa"], block_size=50)
        self.assertEqual([len(bloque) for bloque in bloques], [200, 1])

    def test_tamano_del_bloque_coincide_con_el_limite(self):
        documentos = [f"casa{i} gato{i} perro{i}" for i in range(100)]
        limite = 300
        _, paths, _ = self.build(documentos, block_size=limite)
        self.assertGreater(len(paths), 1)
        for path in paths[:-1]:
            # Se pasa como mucho lo que ocupa un documento: 3 términos nuevos.
            self.assertGreaterEqual(os.path.getsize(path), limite)
            self.assertLess(os.path.getsize(path), limite + 3 * (BLOCK_ENTRY.size + 12 + POSTING.size))

    def test_documento_sin_terminos_consume_su_doc_id(self):
        bloques, _, siguiente = self.build(["casa", "de la", "", "gato"])
        self.assertEqual(bloques[0], {"cas": [(0, 1)], "gat": [(3, 1)]})
        self.assertEqual(siguiente, 4)

    def test_sin_documentos_no_hay_bloques(self):
        self.assertEqual(self.build([])[0], [])

    def test_descarta_terminos_demasiado_largos(self):
        largo = "ñ" * MAX_TERM_BYTES
        bloques, _, _ = self.build([f"{largo} casa"])
        self.assertEqual(bloques[0], {"cas": [(0, 1)]})

    def test_doc_id_continua_en_la_siguiente_construccion(self):
        with SpimiIndex(self.path) as index:
            primeros = index._build_blocks(["casa"])
            index._remove_blocks(primeros)
            segundos = index._build_blocks(["gato"])
            self.addCleanup(index._remove_blocks, segundos)
            self.assertEqual(dict(read_block(segundos[0])), {"gat": [(1, 1)]})

    def test_error_al_leer_limpia_los_temporales(self):
        def documentos():
            yield "casa"
            yield "gato"
            raise OSError("fallo de lectura")

        with SpimiIndex(self.path, block_size=1) as index:
            with self.assertRaises(OSError):
                index._build_blocks(documentos())
            self.assertEqual(index.next_doc_id, 0)
        self.assertEqual(os.listdir(self.dir), [os.path.basename(self.path)])

    def test_tamano_de_bloque_invalido(self):
        with self.assertRaises(ValueError):
            SpimiIndex(self.path, block_size=0)


if __name__ == "__main__":
    unittest.main()
