"""Asistente académico: BM25 + LLM con citas (#98). El LLM se simula."""

import os
import tempfile
import unittest
from types import SimpleNamespace

from tests.test_papers_corpus import pdf_con_texto
from api.asistente import (MAX_POR_PAPER, SIN_FRAGMENTOS, UMBRAL_RELATIVO, ClienteClaude, ClienteGemini,
                           ErrorLLM, citas, cognados, crear_llm, palabras_clave, palabras_clave_locales,
                           recuperar)

try:
    from fastapi.testclient import TestClient
    from api.main import create_app
except ImportError:  # pragma: no cover - dependencia de requirements-api.txt
    TestClient = None

# Mismo esquema que rag/corpus.py (#97), con tres papers de juguete.
CORPUS = """
CREATE TABLE papers (id INT PRIMARY KEY, arxiv_id TEXT, titulo TEXT, autores TEXT, anio INT,
  abstract TEXT, categoria TEXT, fuente TEXT, url TEXT, licencia TEXT, tema TEXT);
CREATE TABLE fragmentos (id INT PRIMARY KEY, paper_id INT REFERENCES papers(id), orden INT,
  pagina INT, pagina_fin INT, palabras INT, texto TEXT);
INSERT INTO papers VALUES
  (1, '1603.09320', 'Efficient and robust approximate nearest neighbor search using HNSW graphs',
   'Malkov, Yashunin', 2016, '', 'cs.DS', 'arxiv', 'https://arxiv.org/abs/1603.09320v4', 'cc', 'hnsw'),
  (2, '0000.00001', 'The Probabilistic Relevance Framework: BM25 and Beyond', 'Robertson, Zaragoza',
   2009, '', 'cs.IR', 'arxiv', 'https://arxiv.org/abs/0000.00001v1', 'cc', 'bm25'),
  (3, '0000.00002', 'R-trees: a dynamic index structure for spatial searching', 'Guttman', 1984,
   '', 'cs.DB', 'arxiv', 'https://arxiv.org/abs/0000.00002v1', 'cc', 'rtree');
INSERT INTO fragmentos VALUES
  (1, 1, 1, 3, 3, 12, 'HNSW builds a hierarchical navigable small world graph of layers for approximate nearest neighbor search'),
  (2, 1, 2, 4, 5, 10, 'search starts at the top layer of the graph and greedily descends to the nearest neighbor'),
  (3, 2, 1, 7, 7, 11, 'BM25 ranks documents by term frequency with saturation and inverse document frequency'),
  (4, 3, 1, 2, 2, 9, 'an R-tree groups nearby spatial objects in minimum bounding rectangles');
CREATE INDEX fragmentos_texto ON fragmentos (texto) USING SPIMI WITH (LANGUAGE = 'en');
"""


class LLMFalso:
    """Devuelve respuestas fijas y guarda lo que recibió."""

    def __init__(self, palabras="hnsw graph nearest neighbor",
                 respuesta="HNSW usa un grafo jerárquico [1] y baja por capas [2]. Falso [9]."):
        self.palabras, self.respuesta = palabras, respuesta
        self.llamadas = []

    def completar(self, sistema, mensaje, max_tokens):
        self.llamadas.append((sistema, mensaje))
        return self.palabras if len(self.llamadas) == 1 else self.respuesta


class LLMCaido:
    def completar(self, sistema, mensaje, max_tokens):
        raise ErrorLLM("No hay conexión con el LLM")


class TestFunciones(unittest.TestCase):
    def test_palabras_clave_locales_traduce_y_quita_vacias(self):
        consulta = palabras_clave_locales("¿Cómo funciona la búsqueda de vecinos cercanos en HNSW?")
        self.assertEqual(consulta, "search neighbors nearest hnsw")

    def test_palabras_clave_locales_reconoce_frases(self):
        self.assertEqual(palabras_clave_locales("¿Índice aprendido frente a un árbol B+?"),
                         "index learned b-tree")
        self.assertEqual(palabras_clave_locales("bases de datos vectoriales"), "database vector")
        self.assertEqual(palabras_clave_locales("¿Cómo se estima la cardinalidad?"),
                         "estimation cardinality")

    def test_palabras_clave_limpia_la_salida_del_llm(self):
        llm = LLMFalso(palabras="HNSW, graph; 'search'\nnearest-neighbor.")
        self.assertEqual(palabras_clave("pregunta", llm), "hnsw graph search nearest-neighbor")

    def test_palabras_clave_vacias_del_llm_usan_el_glosario(self):
        self.assertEqual(palabras_clave("índice invertido", LLMFalso(palabras="...")), "index inverted")

    def test_cognados_de_la_pregunta(self):
        ingles = "horizontal fragmentation distributed databases partitioning".split()
        self.assertEqual(cognados("¿Qué es la fragmentación horizontal en bases de datos distribuidas?", ingles),
                         ["fragmentacion", "distribuidas"])  # 'horizontal' ya está
        self.assertEqual(cognados("¿Cómo funciona el hashing extensible?", ["extendible", "hashing"]), ["extensible"])
        self.assertEqual(cognados("¿Qué hace el buffer manager?", ["buffer", "manager", "page"]), [])

    def test_palabras_del_llm_mas_cognados(self):
        llm = LLMFalso(palabras="horizontal fragmentation distributed databases partitioning")
        self.assertEqual(palabras_clave("¿Qué es la fragmentación horizontal?", llm),
                         "horizontal fragmentation distributed databases partitioning fragmentacion")

    def test_palabras_del_llm_con_termino_en_espanol(self):
        llm = LLMFalso(palabras="horizontal fragmentation distributed databases partitioning sharding\n"
                                "ES: fragmentacion horizontal de")
        self.assertEqual(palabras_clave("pregunta", llm),
                         "horizontal fragmentation distributed databases partitioning fragmentacion")

    def test_palabras_del_llm_se_recortan_a_las_mas_especificas(self):
        llm = LLMFalso(palabras="spimi inverted index construction block memory algorithm sorting")
        self.assertEqual(palabras_clave("pregunta", llm), "spimi inverted index construction block")

    def test_recuperar_limita_fragmentos_por_paper(self):
        # BM25 devuelve 4 fragmentos del paper 1 antes que los de los papers 2 y 3.
        candidatos = [(i, pid, 30.0 - i) for i, pid in enumerate([1, 1, 1, 1, 2, 3, 2], start=1)]
        consultas = []

        def ejecutar(sql):
            consultas.append(sql)
            if "FROM fragmentos" in sql:
                return SimpleNamespace(tiene_error=False, error=None,
                                       columnas=["id", "paper_id", "pagina", "pagina_fin", "texto", "puntaje"],
                                       filas=[(i, pid, 1, 1, f"t{i}", s) for i, pid, s in candidatos])
            return SimpleNamespace(tiene_error=False, error=None, columnas=["id", "titulo", "autores", "anio", "url"],
                                   filas=[(pid, f"P{pid}", "", 2020, "") for pid in (1, 2, 3)])

        fragmentos = recuperar(ejecutar, "hnsw", 4)
        self.assertEqual([f["id"] for f in fragmentos], [1, 2, 5, 6])  # el 3.º y 4.º del paper 1 se saltan
        self.assertEqual(MAX_POR_PAPER, 2)
        self.assertIn("LIMIT 20", consultas[0])  # se piden más candidatos que k

    def test_recuperar_anota_que_paso_con_cada_candidato(self):
        candidatos = [(i, pid, 30.0 - i) for i, pid in enumerate([1, 1, 1, 2, 3, 2, 4], start=1)]
        candidatos.append((8, 5, 10.0))  # bajo el 70 % del primero (29 * 0.7 = 20.3)

        def ejecutar(sql):
            if "FROM fragmentos" in sql:
                return SimpleNamespace(tiene_error=False, error=None,
                                       columnas=["id", "paper_id", "pagina", "pagina_fin", "texto", "puntaje"],
                                       filas=[(i, pid, 1, 1, f"t{i}", s) for i, pid, s in candidatos])
            return SimpleNamespace(tiene_error=False, error=None, columnas=["id", "titulo", "autores", "anio", "url", "fuente"],
                                   filas=[(pid, f"P{pid}", "", 2020, "", "arxiv") for pid in range(1, 6)])

        detalle = {}
        elegidos = recuperar(ejecutar, "hnsw", 4, detalle)
        self.assertEqual([f["id"] for f in elegidos], [1, 2, 4, 5])
        self.assertEqual([c["estado"] for c in detalle["candidatos"]],
                         ["elegido", "elegido", "por_documento", "elegido", "elegido", "sobra", "sobra", "umbral"])
        self.assertEqual([c["n"] for c in detalle["candidatos"]], [1, 2, None, 3, 4, None, None, None])
        self.assertEqual(detalle["umbral"], 20.3)
        self.assertEqual(detalle["candidatos"][0]["titulo"], "P1")

    def test_recuperar_descarta_puntajes_bajos(self):
        # Con el primero en 10.0, todo lo que quede bajo el 70 % (7.0) se descarta.
        candidatos = [(1, 1, 10.0), (2, 2, 7.5), (3, 3, 7.0), (4, 4, 6.9), (5, 5, 2.0)]

        def ejecutar(sql):
            if "FROM fragmentos" in sql:
                return SimpleNamespace(tiene_error=False, error=None,
                                       columnas=["id", "paper_id", "pagina", "pagina_fin", "texto", "puntaje"],
                                       filas=[(i, pid, 1, 1, f"t{i}", s) for i, pid, s in candidatos])
            return SimpleNamespace(tiene_error=False, error=None, columnas=["id", "titulo", "autores", "anio", "url"],
                                   filas=[(pid, f"P{pid}", "", 2020, "") for pid in range(1, 6)])

        self.assertEqual(UMBRAL_RELATIVO, 0.7)
        self.assertEqual([f["id"] for f in recuperar(ejecutar, "hnsw", 5)], [1, 2, 3])

    def test_citas_validas_sin_repetir_y_en_orden(self):
        self.assertEqual(citas("a [2] b [1, 3] c [2] d [7] e [0]", total=3), [2, 1, 3])
        self.assertEqual(citas("sin citas", total=3), [])


class ClienteAnthropicFalso:
    def __init__(self, stop_reason="end_turn"):
        self.peticion = None
        self.stop_reason = stop_reason
        self.messages = self

    def create(self, **peticion):
        self.peticion = peticion
        return SimpleNamespace(stop_reason=self.stop_reason, content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="Hola "),
            SimpleNamespace(type="text", text="[1]"),
        ])


class TestClienteClaude(unittest.TestCase):
    def test_arma_la_peticion_y_une_los_bloques_de_texto(self):
        falso = ClienteAnthropicFalso()
        texto = ClienteClaude(modelo="claude-haiku-5-5", cliente=falso).completar("sis", "msg", 100)
        self.assertEqual(texto, "Hola [1]")
        self.assertEqual(falso.peticion["model"], "claude-haiku-5-5")
        self.assertEqual(falso.peticion["system"], "sis")
        self.assertEqual(falso.peticion["messages"], [{"role": "user", "content": "msg"}])
        self.assertEqual(falso.peticion["max_tokens"], 100)

    def test_rechazo_del_modelo_es_error(self):
        with self.assertRaises(ErrorLLM):
            ClienteClaude(cliente=ClienteAnthropicFalso("refusal")).completar("s", "m", 10)

    def test_modelo_por_variable_de_entorno(self):
        anterior = os.environ.get("BD2_LLM_MODELO")
        os.environ["BD2_LLM_MODELO"] = "claude-sonnet-5-5"
        try:
            self.assertEqual(ClienteClaude().modelo, "claude-sonnet-5-5")
        finally:
            if anterior is None:
                del os.environ["BD2_LLM_MODELO"]
            else:
                os.environ["BD2_LLM_MODELO"] = anterior


class ClienteGeminiFalso:
    def __init__(self, texto="Hola [1]", bloqueo=None, error=None):
        self.peticion = None
        self.texto, self.bloqueo, self.error = texto, bloqueo, error
        self.models = self

    def generate_content(self, **peticion):
        self.peticion = peticion
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.texto, prompt_feedback=SimpleNamespace(block_reason=self.bloqueo))


class TestClienteGemini(unittest.TestCase):
    def test_arma_la_peticion(self):
        falso = ClienteGeminiFalso(texto="  Hola [1]\n")
        texto = ClienteGemini(modelo="gemini-x", cliente=falso).completar("sis", "msg", 100)
        self.assertEqual(texto, "Hola [1]")
        self.assertEqual(falso.peticion["model"], "gemini-x")
        self.assertEqual(falso.peticion["contents"], "msg")
        self.assertEqual(falso.peticion["config"].system_instruction, "sis")
        self.assertEqual(falso.peticion["config"].max_output_tokens, 100)

    def test_respuesta_vacia_y_bloqueo(self):
        self.assertEqual(ClienteGemini(cliente=ClienteGeminiFalso(texto=None)).completar("s", "m", 9), "")
        with self.assertRaises(ErrorLLM):
            ClienteGemini(cliente=ClienteGeminiFalso(bloqueo="SAFETY")).completar("s", "m", 9)

    def test_cuota_agotada_es_error_claro(self):
        from google.genai import errors

        error = errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})
        with self.assertRaisesRegex(ErrorLLM, "cuota"):
            ClienteGemini(cliente=ClienteGeminiFalso(error=error)).completar("s", "m", 9)


class TestCrearLLM(unittest.TestCase):
    def test_proveedores(self):
        self.assertIsInstance(crear_llm("gemini"), ClienteGemini)
        self.assertIsInstance(crear_llm("Claude"), ClienteClaude)
        self.assertIsNone(crear_llm("ninguno"))
        with self.assertRaises(ValueError):
            crear_llm("gpt")

    def test_gemini_por_defecto(self):
        anterior = os.environ.pop("BD2_LLM", None)
        try:
            self.assertIsInstance(crear_llm(), ClienteGemini)
        finally:
            if anterior is not None:
                os.environ["BD2_LLM"] = anterior


@unittest.skipIf(TestClient is None, "requiere requirements-api.txt")
class TestEndpoint(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.datos = os.path.join(temp.name, "datos")
        self.papers = os.path.join(temp.name, "papers")
        os.makedirs(os.path.join(self.papers, "pdf"))

    def abrir(self, llm, corpus=True):
        cliente = TestClient(create_app(directorio=self.datos, carpetas_archivos=[], llm=llm,
                                        carpeta_papers=self.papers))
        cliente.__enter__()
        self.addCleanup(cliente.__exit__, None, None, None)
        if corpus:
            respuesta = cliente.post("/sql", json={"sql": CORPUS})
            self.assertEqual(respuesta.status_code, 200, respuesta.text)
        return cliente

    def preguntar(self, cliente, estado=200, **cuerpo):
        respuesta = cliente.post("/asistente/preguntar",
                                 json={"pregunta": "¿Cómo funciona HNSW?", **cuerpo})
        self.assertEqual(respuesta.status_code, estado, respuesta.text)
        return respuesta.json()

    def test_respuesta_con_citas_y_fragmentos(self):
        llm = LLMFalso()
        datos = self.preguntar(self.abrir(llm), k=3)
        self.assertEqual(datos["modo"], "llm")
        self.assertEqual(datos["consulta"], "hnsw graph nearest neighbor")
        self.assertEqual(datos["respuesta"], llm.respuesta)
        self.assertEqual(datos["citas"], [1, 2])  # [9] no existe y se descarta
        fragmentos = datos["fragmentos"]
        self.assertEqual([f["n"] for f in fragmentos], list(range(1, len(fragmentos) + 1)))
        self.assertEqual({f["paper_id"] for f in fragmentos[:2]}, {1})
        primero = fragmentos[0]
        self.assertEqual(primero["titulo"],
                         "Efficient and robust approximate nearest neighbor search using HNSW graphs")
        self.assertEqual((primero["anio"], primero["url"]), (2016, "https://arxiv.org/abs/1603.09320v4"))
        self.assertIn("pagina", primero)
        puntajes = [f["puntaje"] for f in fragmentos]
        self.assertEqual(puntajes, sorted(puntajes, reverse=True))
        # El LLM recibe los fragmentos numerados con título y página, y la pregunta.
        sistema, mensaje = llm.llamadas[1]
        self.assertIn("SOLO", sistema)
        self.assertIn("[1] Efficient and robust", mensaje)
        self.assertIn("pág. 3", mensaje)
        self.assertIn("Pregunta: ¿Cómo funciona HNSW?", mensaje)

    def test_modo_sin_llm_solo_devuelve_fragmentos(self):
        llm = LLMFalso()
        datos = self.preguntar(self.abrir(llm), usar_llm=False,
                               pregunta="¿Cómo funciona el ranking BM25 por frecuencia de términos?")
        self.assertEqual(llm.llamadas, [])
        self.assertEqual(datos["modo"], "sin_llm")
        self.assertIsNone(datos["respuesta"])
        self.assertEqual(datos["citas"], [])
        self.assertEqual(datos["fragmentos"][0]["paper_id"], 2)

    def test_app_sin_llm(self):
        datos = self.preguntar(self.abrir(None))
        self.assertEqual(datos["modo"], "sin_llm")
        self.assertTrue(datos["fragmentos"])

    def test_sin_fragmentos_no_llama_al_llm_para_responder(self):
        llm = LLMFalso(palabras="quantum chromodynamics")
        datos = self.preguntar(self.abrir(llm))
        self.assertEqual(len(llm.llamadas), 1)  # solo las palabras clave
        self.assertEqual(datos["fragmentos"], [])
        self.assertEqual(datos["respuesta"], SIN_FRAGMENTOS)

    def test_sin_corpus_cargado_es_400(self):
        datos = self.preguntar(self.abrir(LLMFalso(), corpus=False), estado=400)
        self.assertIn("rag.corpus", datos["error"])

    def test_palabras_clave_locales_llaman_al_llm_una_vez(self):
        llm = LLMFalso(respuesta="El ranking usa BM25 [1].")
        anterior = os.environ.get("BD2_PALABRAS_CLAVE")
        os.environ["BD2_PALABRAS_CLAVE"] = "local"
        try:
            cliente = self.abrir(llm)
        finally:
            if anterior is None:
                del os.environ["BD2_PALABRAS_CLAVE"]
            else:
                os.environ["BD2_PALABRAS_CLAVE"] = anterior
        llm.llamadas.append(("ya", "se usaron las palabras"))  # la siguiente llamada es la respuesta
        datos = self.preguntar(cliente, pregunta="¿Cómo funciona el ranking BM25 por frecuencia de términos?")
        self.assertEqual(len(llm.llamadas), 2)  # la marca de arriba + una sola llamada real
        self.assertEqual(datos["consulta"], palabras_clave_locales(datos["pregunta"]))
        self.assertEqual(datos["respuesta"], "El ranking usa BM25 [1].")

    def test_error_del_llm_es_502(self):
        datos = self.preguntar(self.abrir(LLMCaido()), estado=502)
        self.assertIn("conexión", datos["error"])

    def test_validaciones(self):
        cliente = self.abrir(LLMFalso())
        self.preguntar(cliente, estado=422, k=50)
        self.preguntar(cliente, estado=400, pregunta="   ")

    # --- traza, biblioteca y subida (#99) -------------------------------

    def test_traza_de_lo_que_hizo_el_motor(self):
        traza = self.preguntar(self.abrir(LLMFalso()), k=3)["traza"]
        self.assertEqual(len(traza["sql"]), 2)
        self.assertIn("USING BM25", traza["sql"][0])
        self.assertIn("FROM papers WHERE id IN", traza["sql"][1])
        self.assertGreaterEqual(traza["ms_motor"], 0)
        self.assertTrue(traza["palabras_con_llm"])
        self.assertIsNotNone(traza["s_redaccion"])
        self.assertGreaterEqual(traza["s_total"], 0)
        sin_llm = self.preguntar(self.abrir(None, corpus=False))["traza"]
        self.assertFalse(sin_llm["palabras_con_llm"])
        self.assertIsNone(sin_llm["s_redaccion"])

    def test_estado_del_asistente(self):
        self.assertEqual(self.abrir(None, corpus=False).get("/asistente/estado").json(),
                         {"corpus": False, "documentos": None, "fragmentos": None, "llm": None,
                          "palabras_con_llm": True})

    def test_estado_con_corpus(self):
        estado = self.abrir(ClienteGemini(modelo="gemini-x")).get("/asistente/estado").json()
        self.assertEqual((estado["corpus"], estado["documentos"], estado["fragmentos"], estado["llm"]),
                         (True, 3, 4, "gemini-x"))

    def test_biblioteca_y_detalle(self):
        cliente = self.abrir(None)
        documentos = cliente.get("/asistente/documentos").json()
        self.assertEqual([(d["id"], d["fragmentos"]) for d in documentos], [(1, 2), (2, 1), (3, 1)])
        self.assertEqual(documentos[0]["anio"], 2016)
        detalle = cliente.get("/asistente/documentos/1").json()
        self.assertEqual([f["orden"] for f in detalle["fragmentos"]], [1, 2])
        self.assertIn("abstract", detalle)
        self.assertEqual(cliente.get("/asistente/documentos/99").status_code, 404)

    def test_pdf_del_documento(self):
        with open(os.path.join(self.papers, "pdf", "1603.09320.pdf"), "wb") as fh:
            fh.write(pdf_con_texto(["HNSW"]))
        cliente = self.abrir(None)
        respuesta = cliente.get("/asistente/documentos/1/pdf")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.headers["content-type"], "application/pdf")
        self.assertEqual(cliente.get("/asistente/documentos/2/pdf").status_code, 404)  # no descargado

    def test_subir_pdf_lo_fragmenta_y_lo_indexa(self):
        cliente = self.abrir(None)
        pdf = pdf_con_texto(["Single pass in memory indexing builds one dictionary per block",
                             "SPIMI merges the blocks at the end"])
        respuesta = cliente.post("/asistente/documentos", files={"archivo": ("clase08.pdf", pdf, "application/pdf")},
                                 data={"titulo": "Clase 08: SPIMI", "autores": "Docente", "anio": "2026",
                                       "tipo": "clase"})
        self.assertEqual(respuesta.status_code, 200, respuesta.text)
        datos = respuesta.json()
        self.assertEqual((datos["id"], datos["paginas"], datos["fragmentos"]), (4, 2, 1))
        self.assertTrue(os.path.isfile(os.path.join(self.papers, "subidos", "4.pdf")))
        documentos = cliente.get("/asistente/documentos").json()
        self.assertEqual((documentos[-1]["titulo"], documentos[-1]["fuente"]), ("Clase 08: SPIMI", "curso"))
        encontrado = cliente.post("/sql", json={"sql": "SELECT paper_id FROM fragmentos WHERE "
                                                       "MATCH(texto, 'spimi dictionary') USING BM25 LIMIT 1"})
        self.assertEqual(encontrado.json()["filas"], [[4]])  # el índice SPIMI ya lo tiene
        self.assertEqual(cliente.get("/asistente/documentos/4/pdf").status_code, 200)

    def test_subir_rechaza_lo_que_no_es_pdf(self):
        cliente = self.abrir(None)
        respuesta = cliente.post("/asistente/documentos", files={"archivo": ("x.pdf", b"hola", "application/pdf")},
                                 data={"titulo": "X", "anio": "2026"})
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(len(cliente.get("/asistente/documentos").json()), 3)


if __name__ == "__main__":
    unittest.main()
