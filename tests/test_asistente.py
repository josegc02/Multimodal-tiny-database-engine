"""Asistente académico: BM25 + LLM con citas (#98). El LLM se simula."""

import os
import tempfile
import unittest
from types import SimpleNamespace

from api.asistente import (SIN_FRAGMENTOS, ClienteClaude, ErrorLLM, citas, palabras_clave,
                           palabras_clave_locales)

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


@unittest.skipIf(TestClient is None, "requiere requirements-api.txt")
class TestEndpoint(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.datos = temp.name

    def abrir(self, llm, corpus=True):
        cliente = TestClient(create_app(directorio=self.datos, carpetas_archivos=[], llm=llm))
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

    def test_error_del_llm_es_502(self):
        datos = self.preguntar(self.abrir(LLMCaido()), estado=502)
        self.assertIn("conexión", datos["error"])

    def test_validaciones(self):
        cliente = self.abrir(LLMFalso())
        self.preguntar(cliente, estado=422, k=50)
        self.preguntar(cliente, estado=400, pregunta="   ")


if __name__ == "__main__":
    unittest.main()
