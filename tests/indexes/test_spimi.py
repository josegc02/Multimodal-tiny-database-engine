import math
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import frontend.motor as motor_module
from engine.indexes import spimi
from engine.indexes.spimi import (BLOCK_ENTRY, DOCUMENTS_PER_PAGE, HEADER, MAX_TERM_BYTES, PAGE_SIZE, POSTING,
                                  SpimiIndex, decode_dictionary_page, decode_postings, encode_postings, pages_for,
                                  read_block, tf_weight)
from engine.query.planner import IndexInfo
from engine.storage.record import RID


def con_rid(textos):
    return [(texto, RID(i, 0)) for i, texto in enumerate(textos)]


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
            paths = index._build_blocks(con_rid(documents))
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
            primeros = index._build_blocks(con_rid(["casa"]))
            index._remove_blocks(primeros)
            segundos = index._build_blocks(con_rid(["gato"]))
            self.addCleanup(index._remove_blocks, segundos)
            self.assertEqual(dict(read_block(segundos[0])), {"gat": [(1, 1)]})

    def test_error_al_leer_limpia_los_temporales(self):
        def documentos():
            yield "casa", RID(0, 0)
            yield "gato", RID(0, 1)
            raise OSError("fallo de lectura")

        with SpimiIndex(self.path, block_size=1) as index:
            with self.assertRaises(OSError):
                index._build_blocks(documentos())
            self.assertEqual((index.next_doc_id, index.doc_count, index.total_length), (0, 0, 0))
        self.assertEqual(os.listdir(self.dir), [os.path.basename(self.path)])

    def test_tamano_de_bloque_invalido(self):
        with self.assertRaises(ValueError):
            SpimiIndex(self.path, block_size=0)


def contenido(index):
    """Lee el índice completo desde sus páginas: término -> (df, postings)."""
    zona = index._read_pages(index.postings_start, index.postings_pages)
    resultado = {}
    for page in range(index.dictionary_pages):
        for term, df, inicio in decode_dictionary_page(index._read_pages(index.dictionary_start + page)):
            resultado[term] = df, decode_postings(zona[inicio:inicio + df * POSTING.size])
    return resultado


class TestMezcla(SpimiTestCase):
    def merge(self, *bloques):
        with SpimiIndex(self.path) as index:
            paths = []
            for bloque in bloques:
                index._write_block(bloque, paths)
            index._merge_blocks(paths)
            index._remove_blocks(paths)
            return contenido(index)

    def test_ejemplo_de_la_clase(self):
        # Clase 09, diapositiva 9: los términos repetidos concatenan sus listas.
        lista = lambda *docs: [(doc, 1) for doc in docs]
        indice = self.merge(
            {"brutus": lista(1, 3), "caesar": lista(1, 2, 4), "noble": lista(5), "with": lista(1, 2, 3, 5)},
            {"brutus": lista(6, 7), "caesar": lista(8, 9), "julius": lista(10), "killed": lista(8)},
        )
        self.assertEqual(indice, {
            "brutus": (4, lista(1, 3, 6, 7)),
            "caesar": (5, lista(1, 2, 4, 8, 9)),
            "julius": (1, lista(10)),
            "killed": (1, lista(8)),
            "noble": (1, lista(5)),
            "with": (4, lista(1, 2, 3, 5)),
        })

    def test_termino_en_todos_los_bloques(self):
        bloques = [{"casa": [(i, i + 1)]} for i in range(20)]
        self.assertEqual(self.merge(*bloques), {"casa": (20, [(i, i + 1) for i in range(20)])})

    def test_listas_ocupan_paginas_seguidas(self):
        larga = [(i, 1) for i in range(1500)]
        indice = self.merge({"casa": larga[:800], "gato": [(0, 2)]}, {"casa": larga[800:]})
        self.assertEqual(indice, {"casa": (1500, larga), "gato": (1, [(0, 2)])})
        self.assertEqual(os.path.getsize(self.path), 5 * PAGE_SIZE)  # cabecera, 3 de postings, diccionario

    def test_listas_comparten_pagina(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid([f"palabra{i}" for i in range(50)]))
            self.assertEqual(index.term_count, 50)
            self.assertEqual(index.postings_pages, 1)

    def test_diccionario_de_varias_paginas(self):
        terminos = {f"{i:04d}{'x' * 200}": [(i, 1)] for i in range(300)}
        indice = self.merge(terminos)
        self.assertEqual(list(indice), sorted(terminos))
        self.assertEqual(len(indice), 300)


class TestBuild(SpimiTestCase):
    DOCUMENTOS = ["casa grande", "casa bonita", "gato grande", "perro y gato"]

    def test_construye_y_persiste(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid(self.DOCUMENTOS))
        with SpimiIndex(self.path) as index:
            self.assertEqual(index.term_count, 5)
            self.assertEqual(contenido(index), {
                "bonit": (1, [(1, 1)]),
                "cas": (2, [(0, 1), (1, 1)]),
                "gat": (2, [(2, 1), (3, 1)]),
                "grand": (2, [(0, 1), (2, 1)]),
                "perr": (1, [(3, 1)]),
            })

    def test_no_deja_temporales(self):
        with SpimiIndex(self.path, block_size=1) as index:
            index.build(con_rid(self.DOCUMENTOS))
        self.assertEqual(os.listdir(self.dir), [os.path.basename(self.path)])

    def test_mismo_archivo_con_cualquier_tamano_de_bloque(self):
        archivos = set()
        for block_size in (1, 40, 10_000):
            with SpimiIndex(self.path, block_size=block_size) as index:
                index.build(con_rid(self.DOCUMENTOS * 50))
            with open(self.path, "rb") as f:
                archivos.add(f.read())
            os.remove(self.path)
        self.assertEqual(len(archivos), 1)

    def test_coleccion_vacia(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid([]))
            self.assertEqual(contenido(index), {})
            self.assertEqual((index.term_count, index.page_count), (0, 1))
        self.assertEqual(os.path.getsize(self.path), PAGE_SIZE)

    def test_reconstruir_reemplaza_el_contenido(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid(self.DOCUMENTOS))
            index.build(con_rid(["ratón"]))
            self.assertEqual(contenido(index), {"raton": (1, [(0, 1)])})
            self.assertEqual(index.next_doc_id, 1)

    def test_error_en_la_mezcla_deja_el_indice_vacio(self):
        with SpimiIndex(self.path, block_size=1) as index:
            with patch.object(spimi.shutil, "copyfileobj", side_effect=OSError("disco lleno")):
                with self.assertRaises(OSError):
                    index.build(con_rid(self.DOCUMENTOS))
            self.assertEqual(contenido(index), {})
            self.assertEqual(index.page_count, 1)
        self.assertEqual(os.listdir(self.dir), [os.path.basename(self.path)])


class TestDocumentos(SpimiTestCase):
    def build(self, documentos):
        index = SpimiIndex(self.path)
        self.addCleanup(index.close)
        index.build(documentos)
        return index

    def test_norma_de_la_diapositiva_68(self):
        index = self.build(con_rid(["seguro de carro, seguro de auto"]))
        documento = index.document(0)
        self.assertEqual(documento.length, 4)  # "de" es stopword
        self.assertAlmostEqual(documento.norm, 1.92, places=2)
        self.assertAlmostEqual(documento.norm, math.sqrt(1 + 1 + tf_weight(2) ** 2))

    def test_peso_del_tf(self):
        self.assertEqual([round(tf_weight(tf), 1) for tf in (1, 2, 10, 1000)], [1, 1.3, 2, 4])

    def test_devuelve_el_rid_de_cada_archivo(self):
        documentos = [("casa", RID(7, 3)), ("gato", RID(70_000, 65_000, "aux"))]
        index = self.build(documentos)
        self.assertEqual(index.document(0).rid, RID(7, 3))
        self.assertEqual(index.document(1).rid, RID(70_000, 65_000, "aux"))

    def test_totales_y_longitud_promedio(self):
        index = self.build(con_rid(["casa casa gato", "perro", "de la"]))
        self.assertEqual([index.document(i).length for i in range(3)], [3, 1, 0])
        self.assertEqual((index.doc_count, index.total_length), (3, 4))
        self.assertAlmostEqual(index.average_length, 4 / 3)

    def test_documento_sin_terminos_tiene_norma_cero(self):
        index = self.build(con_rid(["casa", "", "gato"]))
        self.assertEqual(index.document(1).norm, 0)
        self.assertEqual(index.document(2).rid, RID(2, 0))

    def test_tabla_de_varias_paginas(self):
        cantidad = 2 * DOCUMENTS_PER_PAGE + 5
        index = self.build(con_rid(["casa"] * cantidad))
        self.assertEqual(index.documents_pages, 3)
        for doc_id in (0, DOCUMENTS_PER_PAGE - 1, DOCUMENTS_PER_PAGE, cantidad - 1):
            with self.subTest(doc_id=doc_id):
                self.assertEqual(index.document(doc_id).rid, RID(doc_id, 0))

    def test_consultar_un_documento_lee_una_pagina(self):
        index = self.build(con_rid(["casa"] * 500))
        with patch.object(index, "_read_pages", wraps=index._read_pages) as lectura:
            index.document(450)
        lectura.assert_called_once_with(index.documents_start + 2)

    def test_persiste_al_reabrir(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid(["seguro seguro auto"]))
            norma = index.document(0).norm
        with SpimiIndex(self.path) as index:
            self.assertEqual(index.document(0).norm, norma)
            self.assertEqual((index.doc_count, index.total_length), (1, 3))

    def test_el_archivo_ocupa_lo_que_dice_la_cabecera(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid(["casa grande"] * 300))
            paginas = index.page_count
        self.assertEqual(os.path.getsize(self.path), paginas * PAGE_SIZE)

    def test_coleccion_vacia(self):
        index = self.build([])
        self.assertEqual((index.documents_pages, index.average_length), (0, 0.0))

    def test_doc_id_fuera_de_rango(self):
        index = self.build(con_rid(["casa"]))
        for doc_id in (-1, 1):
            with self.subTest(doc_id=doc_id), self.assertRaises(IndexError):
                index.document(doc_id)

    def test_no_deja_temporales(self):
        self.build(con_rid(["casa"]))
        self.assertEqual(os.listdir(self.dir), [os.path.basename(self.path)])


class TestLectura(SpimiTestCase):
    def open(self, documentos):
        with SpimiIndex(self.path) as index:
            index.build(con_rid(documentos))
        index = SpimiIndex(self.path)
        self.addCleanup(index.close)
        return index

    def test_postings_y_df(self):
        index = self.open(["casa grande", "casa casa bonita", "gato"])
        self.assertEqual(index.postings("cas"), [(0, 1), (1, 2)])
        self.assertEqual(index.df("cas"), 2)
        self.assertEqual(index.df("gat"), 1)

    def test_termino_inexistente(self):
        index = self.open(["casa grande"])
        for termino in ("aaa", "cat", "zzz"):  # antes, entre y después de los términos
            with self.subTest(termino=termino):
                self.assertEqual(index.postings(termino), [])
                self.assertEqual(index.df(termino), 0)

    def test_indice_vacio(self):
        index = self.open([])
        self.assertEqual(index.postings("cas"), [])
        self.assertEqual(list(index.terms()), [])

    def test_analyze_usa_el_pipeline_de_los_documentos(self):
        index = self.open(["las casas grandes"])
        self.assertEqual(index.analyze("La CASA y las casas"), {"cas": 2})
        self.assertEqual(index.analyze(None), {})
        self.assertEqual(index.postings("cas"), [(0, 1)])

    def test_listas_que_cruzan_paginas(self):
        # Antes de "zorro" hay muchas listas, así que empieza a mitad de página.
        documentos = [f"palabra{i} zorro" for i in range(600)]
        index = self.open(documentos)
        self.assertEqual(index.postings("zorr"), [(i, 1) for i in range(600)])

    def test_diccionario_de_varias_paginas(self):
        terminos = {f"{i:04d}{'x' * 200}": [(i, 1)] for i in range(300)}
        with SpimiIndex(self.path) as index:
            paths = []
            index._write_block(terminos, paths)
            index._merge_blocks(paths)
            index._remove_blocks(paths)
            self.assertGreater(index.dictionary_pages, 1)
            for term, postings in terminos.items():
                self.assertEqual(index.postings(term), postings)

    def test_interseccion_de_la_clase(self):
        # Clase 07, diapositiva 78: Bruto AND Cesar = 2, 8.
        with SpimiIndex(self.path) as index:
            paths = []
            index._write_block({"bruto": [(d, 1) for d in (2, 4, 8, 16, 32, 64, 128)],
                                "cesar": [(d, 1) for d in (1, 2, 3, 5, 8, 13, 21, 34)]}, paths)
            index._merge_blocks(paths)
            index._remove_blocks(paths)
            bruto, cesar = ({d for d, _ in index.postings(t)} for t in ("bruto", "cesar"))
            self.assertEqual(sorted(bruto & cesar), [2, 8])

    def test_terms_recorre_en_orden(self):
        index = self.open(["casa grande", "gato"])
        self.assertEqual([(t, df) for t, df, _ in index.terms()], [("cas", 1), ("gat", 1), ("grand", 1)])

    def test_cuenta_lecturas(self):
        index = self.open([f"palabra{i}" for i in range(100)] + ["casa"] * 50)
        index.postings("cas")  # carga el índice del diccionario
        index.reset_stats()
        index.postings("cas")
        self.assertEqual(index.stats.postings_read, 50)
        self.assertEqual(index.stats.pages_read, 2)  # diccionario + lista

    def test_abrir_no_reconstruye(self):
        self.open(["casa"])
        with patch.object(SpimiIndex, "_build_blocks", side_effect=AssertionError("no debe reconstruir")):
            with SpimiIndex(self.path) as index:
                self.assertEqual(index.postings("cas"), [(0, 1)])

    def test_abrir_no_lee_el_diccionario(self):
        self.open(["casa"])
        with SpimiIndex(self.path) as index:
            self.assertEqual(index.stats.pages_read, 0)

    def test_reconstruir_actualiza_el_indice_del_diccionario(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid(["casa"]))
            self.assertEqual(index.df("cas"), 1)
            index.build(con_rid(["gato"]))
            self.assertEqual((index.df("cas"), index.df("gat")), (0, 1))


class TestMantenimiento(SpimiTestCase):
    def open(self, documentos=(), **opciones):
        index = SpimiIndex(self.path, **opciones)
        self.addCleanup(index.close)
        if documentos:
            index.build(con_rid(documentos))
        return index

    def test_insertar_y_buscar(self):
        index = self.open(["casa grande"])
        index.insert("casa bonita", RID(9, 0))
        self.assertEqual(index.postings("cas"), [(0, 1), (1, 1)])
        self.assertEqual(index.postings("bonit"), [(1, 1)])
        self.assertEqual((index.df("cas"), index.doc_count, index.total_length), (2, 2, 4))
        self.assertEqual(index.document(1).rid, RID(9, 0))

    def test_insertar_en_indice_vacio(self):
        index = self.open()
        index.insert("casa", RID(0, 0))
        self.assertEqual(index.postings("cas"), [(0, 1)])

    def test_norma_del_delta_es_exacta(self):
        index = self.open(["casa"])
        index.insert("seguro de carro, seguro de auto", RID(1, 0))
        self.assertAlmostEqual(index.document(1).norm, 1.92, places=2)

    def test_eliminar(self):
        index = self.open(["casa grande", "casa bonita"])
        self.assertTrue(index.delete("casa grande", RID(0, 0)))
        self.assertEqual(index.postings("cas"), [(1, 1)])
        self.assertEqual(index.postings("grand"), [])
        self.assertEqual((index.doc_count, index.total_length), (1, 2))
        with self.assertRaises(IndexError):
            index.document(0)

    def test_df_cuenta_borrados_hasta_consolidar(self):
        index = self.open(["casa", "casa"])
        index.delete("casa", RID(0, 0))
        self.assertEqual(index.df("cas"), 2)
        index.consolidate()
        self.assertEqual(index.df("cas"), 1)

    def test_eliminar_del_delta(self):
        index = self.open(["casa"])
        index.insert("gato", RID(5, 0))
        self.assertTrue(index.delete("gato", RID(5, 0)))
        self.assertEqual(index.postings("gat"), [])
        self.assertEqual(index.doc_count, 1)

    def test_eliminar_rid_desconocido(self):
        index = self.open(["casa"])
        self.assertFalse(index.delete("casa", RID(99, 0)))
        self.assertEqual(index.doc_count, 1)

    def test_rid_reutilizado(self):
        index = self.open(["casa"])
        index.delete("casa", RID(0, 0))
        index.insert("gato", RID(0, 0))
        self.assertTrue(index.delete("gato", RID(0, 0)))
        self.assertEqual((index.postings("cas"), index.postings("gat")), ([], []))

    def test_reabrir_con_cambios_pendientes(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid(["casa", "gato"]))
            index.insert("perro", RID(9, 0))
            index.delete("gato", RID(1, 0))
        with SpimiIndex(self.path) as index:
            self.assertEqual(index.postings("perr"), [(2, 1)])
            self.assertEqual(index.postings("gat"), [])
            self.assertEqual((index.doc_count, index.next_doc_id, index.total_length), (2, 3, 2))
            index.insert("zorro", RID(10, 0))
            self.assertEqual(index.postings("zorr"), [(3, 1)])
        with SpimiIndex(self.path) as index:
            self.assertEqual(index.doc_count, 3)

    def test_ultima_escritura_cortada_se_descarta(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid(["casa"]))
            index.insert("gato", RID(1, 0))
        with open(f"{self.path}.delta", "ab") as log:
            log.write(b'{"op": "insert", "doc"')
        with SpimiIndex(self.path) as index:
            self.assertEqual(index.doc_count, 2)
            index.insert("perro", RID(2, 0))
        with SpimiIndex(self.path) as index:
            self.assertEqual(index.postings("perr"), [(2, 1)])

    def test_log_de_otra_generacion_se_ignora(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid(["casa"]))
            index.insert("gato", RID(1, 0))
            with open(index._log_path, "rb") as log:
                viejo = log.read()
            index.consolidate()
        # Simula una caída entre reemplazar el archivo y borrar el log.
        with open(f"{self.path}.delta", "wb") as log:
            log.write(viejo)
        with SpimiIndex(self.path) as index:
            self.assertEqual(index.doc_count, 2)
            self.assertEqual(index.postings("gat"), [(1, 1)])
        self.assertFalse(os.path.exists(f"{self.path}.delta"))

    def test_consolidar_equivale_a_construir_desde_cero(self):
        with SpimiIndex(self.path) as index:
            index.build([("casa grande", RID(0, 0)), ("gato", RID(1, 0)), ("casa bonita", RID(2, 0))])
            index.delete("gato", RID(1, 0))
            index.insert("perro casa", RID(3, 0))
            index.consolidate()
            self.assertEqual((index.doc_count, index.next_doc_id), (3, 3))
        with open(self.path, "rb") as f:
            consolidado = f.read()
        otro = os.path.join(self.dir, "otro.spimi")
        with SpimiIndex(otro) as index:
            index.build([("casa grande", RID(0, 0)), ("casa bonita", RID(2, 0)), ("perro casa", RID(3, 0))])
        with open(otro, "rb") as f:
            limpio = f.read()
        self.assertEqual(consolidado[PAGE_SIZE:], limpio[PAGE_SIZE:])  # la cabecera difiere en la generación

    def test_consolidar_borra_el_log_y_conserva_el_contenido(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid(["casa"]))
            index.insert("gato", RID(1, 0))
            index.consolidate()
            self.assertFalse(os.path.exists(index._log_path))
            self.assertEqual(index.postings("gat"), [(1, 1)])
        with SpimiIndex(self.path) as index:
            self.assertEqual(index.document(1).rid, RID(1, 0))
        self.assertEqual(os.listdir(self.dir), [os.path.basename(self.path)])

    def test_consolidar_todo_borrado(self):
        index = self.open(["casa"])
        index.delete("casa", RID(0, 0))
        index.consolidate()
        self.assertEqual((index.doc_count, index.term_count, index.page_count), (0, 0, 1))
        index.insert("gato", RID(1, 0))
        self.assertEqual(index.postings("gat"), [(0, 1)])

    def test_sin_cambios_no_consolida(self):
        index = self.open(["casa"])
        with patch.object(index, "_merge", side_effect=AssertionError("no debe consolidar")):
            index.consolidate()

    def test_consolida_solo_al_superar_el_limite(self):
        index = self.open(["casa"] * 100, min_changes=5, merge_ratio=0.2)
        generacion = index.generation
        for i in range(24):  # con 124 documentos el límite es 24,8
            index.insert("gato", RID(1000, i))
        self.assertEqual(index.generation, generacion)
        index.insert("gato", RID(1000, 24))  # 25 >= 0,2 * 125
        self.assertEqual(index.generation, generacion + 1)
        self.assertEqual(index.df("gat"), 25)
        self.assertEqual(index.dictionary_pages, 1)

    def test_error_al_consolidar_no_pierde_datos(self):
        index = self.open(["casa"])
        index.insert("gato", RID(1, 0))
        with patch.object(SpimiIndex, "_copy_documents", side_effect=OSError("disco lleno")):
            with self.assertRaises(OSError):
                index.consolidate()
        self.assertEqual(index.postings("gat"), [(1, 1)])
        self.assertEqual(index.postings("cas"), [(0, 1)])
        self.assertEqual(sorted(os.listdir(self.dir)), sorted([os.path.basename(self.path),
                                                               os.path.basename(index._log_path)]))

    def test_reconstruir_descarta_el_delta(self):
        index = self.open(["casa"])
        index.insert("gato", RID(1, 0))
        index.build(con_rid(["perro"]))
        self.assertEqual((index.postings("gat"), index.doc_count), ([], 1))
        self.assertFalse(os.path.exists(index._log_path))


class TestCatalogo(SpimiTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(motor_module, "DEMO_DIR", self.dir)
        patcher.start()
        # Las limpiezas corren en orden inverso: el motor se cierra antes de borrar el directorio.
        self.addCleanup(patcher.stop)
        self.motor = motor_module.Motor()
        self.addCleanup(self.motor.cerrar)

    def sql(self, consulta):
        resultado = self.motor.ejecutar(consulta)
        self.assertFalse(resultado.tiene_error, resultado.error)
        return resultado

    def tabla(self, using=""):
        self.sql(f"CREATE TABLE docs (id INT PRIMARY KEY, texto VARCHAR(60)) {using}")
        self.sql("INSERT INTO docs VALUES (1, 'casa grande'), (2, 'casa grande roja'), (3, 'gato negro')")
        index = SpimiIndex(self.path)
        self.addCleanup(index.close)
        info = IndexInfo("docs_texto", "texto", index, text=True)
        self.motor.catalog.register_index("docs", "texto", index, info)
        self.storage = self.motor.catalog.table("docs").storage
        return index

    def textos(self, index, consulta):
        return sorted(self.storage.get(rid)["texto"] for rid in index.search(consulta))

    def test_registrar_construye_desde_la_tabla(self):
        index = self.tabla()
        self.assertEqual(index.doc_count, 3)
        self.assertEqual(self.textos(index, "casas"), ["casa grande", "casa grande roja"])

    def test_search_exige_todos_los_terminos(self):
        index = self.tabla()
        self.assertEqual(self.textos(index, "roja casa"), ["casa grande roja"])
        self.assertEqual(self.textos(index, "casa gato"), [])
        self.assertEqual(self.textos(index, "de la"), [])

    def test_insert_y_delete_no_reconstruyen(self):
        index = self.tabla()
        with patch.object(index, "build", side_effect=AssertionError("no debe reconstruir")):
            self.sql("INSERT INTO docs VALUES (4, 'gato gris')")
            self.assertEqual(self.textos(index, "gato"), ["gato gris", "gato negro"])
            self.sql("DELETE FROM docs WHERE id = 3")
            self.assertEqual(self.textos(index, "gato"), ["gato gris"])
        self.assertEqual(index.doc_count, 3)

    def test_rollback_deshace_los_cambios(self):
        index = self.tabla()
        self.sql("BEGIN")
        self.sql("INSERT INTO docs VALUES (4, 'perro')")
        self.sql("DELETE FROM docs WHERE id = 3")
        self.sql("ROLLBACK")
        self.assertEqual(self.textos(index, "perro"), [])
        self.assertEqual(self.textos(index, "gato"), ["gato negro"])

    def test_igualdad_no_usa_el_indice_de_texto(self):
        self.tabla()
        filas = self.sql("SELECT id FROM docs WHERE texto = 'casa grande'").filas
        self.assertEqual([fila[0] for fila in filas], [1])
        plan = "\n".join(str(fila[0]) for fila in self.sql(
            "EXPLAIN SELECT id FROM docs WHERE texto = 'casa grande'").filas)
        self.assertNotIn("docs_texto", plan)

    def test_rows_with_compara_el_valor_exacto(self):
        self.tabla()
        filas = self.motor.catalog.table("docs").rows_with("texto", "casa grande")
        self.assertEqual([registro["id"] for _, registro in filas], [1])

    def test_tabla_sequential_reconstruye_porque_sus_rids_se_mueven(self):
        index = self.tabla("USING SEQUENTIAL")
        self.sql("INSERT INTO docs VALUES (0, 'perro')")
        self.assertEqual(self.textos(index, "perro"), ["perro"])
        self.assertEqual(self.textos(index, "gato"), ["gato negro"])
        self.assertEqual(index.doc_count, 4)

    def test_tabla_btree_reconstruye_porque_sus_rids_se_mueven(self):
        index = self.tabla("USING BTREE")
        self.sql("INSERT INTO docs VALUES (0, 'perro')")
        self.assertEqual(self.textos(index, "perro"), ["perro"])
        self.assertEqual(self.textos(index, "gato"), ["gato negro"])
        self.assertEqual(index.doc_count, 4)

    def test_el_planificador_no_lo_trata_como_indice_de_igualdad(self):
        index = self.tabla()
        self.assertFalse(IndexInfo("docs_texto", "texto", index, text=True).supports_equality)
        self.assertTrue(IndexInfo("docs_texto", "texto", index).supports_equality)


class TestBulkLoad(SpimiTestCase):
    class Tabla:
        class schema:
            fields = ["id", "texto"]

        def scan(self):
            yield RID(0, 0), {"id": 1, "texto": "casa"}
            yield RID(0, 1), {"id": 2, "texto": None}

    def test_reemplaza_el_contenido(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid(["gato"]))
            self.assertEqual(index.bulk_load_from_storage(self.Tabla(), "texto"), 2)
            self.assertEqual((index.df("gat"), index.df("cas")), (0, 1))

    def test_sin_reemplazar_agrega(self):
        with SpimiIndex(self.path) as index:
            index.build(con_rid(["gato"]))
            self.assertEqual(index.bulk_load_from_storage(self.Tabla(), "texto", replace=False), 2)
            self.assertEqual((index.df("gat"), index.df("cas"), index.doc_count), (1, 1, 3))

    def test_campo_inexistente(self):
        with SpimiIndex(self.path) as index, self.assertRaises(ValueError):
            index.bulk_load_from_storage(self.Tabla(), "titulo")


if __name__ == "__main__":
    unittest.main()
