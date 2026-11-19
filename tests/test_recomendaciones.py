import gzip
import json
import threading
import numpy as np
from fastapi.testclient import TestClient

from api.main import create_app
from tienda.recomendaciones import fusionar


def test_top_diez_y_desempate():
    senales = {"compras": {i: 1 for i in range(20)}}
    filas = fusionar(0, senales, {"compras": 1})
    assert [f["id"] for f in filas] == list(range(1, 11))


def test_categoria_reordena_sin_agregar(tmp_path):
    from frontend.motor import Motor
    from tienda.recomendaciones import misma_categoria
    motor = Motor(directorio=str(tmp_path), modo_demo=False)
    motor.ejecutar("CREATE TABLE productos (id INT PRIMARY KEY, categoria TEXT)")
    motor.ejecutar("INSERT INTO productos VALUES (1,'mandos'),(2,'juegos'),(3,'mandos'),(4,'mandos'),(5,'')")
    # 4 es de la misma categoría pero no es candidato: no se agrega.
    assert misma_categoria(motor, "mandos", {2, 3, 5}) == {3: 1}
    assert misma_categoria(motor, "", {2, 3}) == {}  # sin categoría: ni bono ni castigo
    senales = {"texto": {2: 1.0, 3: 0.9}, "categoria": misma_categoria(motor, "mandos", {2, 3})}
    assert [f["id"] for f in fusionar(1, senales, {"texto": 1, "categoria": 0.25})] == [3, 2]
    motor.cerrar()


def test_tienda_http(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for archivo in ("a", "b", "c"):
        (tmp_path / archivo).write_bytes(b"imagen")
    vectores = {"a": [1, 0], "b": [0, 1], "c": [1, 0.1]}
    monkeypatch.setattr("engine.storage.media_store.extract_features",
                        lambda tipo, ruta: np.array(vectores[ruta]))
    from pathlib import Path
    monkeypatch.setattr("tienda.indice_imagen.extractor_for", lambda tipo, nombre: None)  # modelo presente
    otra_peticion = []

    def extraer_mobilenet(tipo, ruta, nombre):
        # Mientras se extraen los vectores, el resto de la API debe seguir respondiendo:
        # la extracción no puede hacerse dentro del lock del motor.
        if not otra_peticion:
            hilo = threading.Thread(target=lambda: otra_peticion.append(cliente.get("/salud").status_code))
            hilo.start()
            hilo.join(timeout=10)
            otra_peticion.append("bloqueada" if hilo.is_alive() else "respondió")
        return np.array(vectores[Path(ruta).name])
    monkeypatch.setattr("tienda.indice_imagen.extract_features", extraer_mobilenet)
    with TestClient(create_app(str(tmp_path), llm=None)) as cliente:
        sql = """
        CREATE TABLE productos(id INT PRIMARY KEY, descripcion TEXT, imagen IMAGE, precio FLOAT, categoria TEXT);
        INSERT INTO productos VALUES (1,'racing console','a',10,'games'),(2,'sports','b',20,'games'),
                                     (3,'racing console','c',30,'games');
        CREATE INDEX img ON productos(imagen) USING HNSW WITH (METRIC=cosine);
        CREATE INDEX txt ON productos(descripcion) USING SPIMI WITH (LANGUAGE='en');
        CREATE TABLE compras(id INT, usuario VARCHAR(20), producto_id INT, fecha INT);
        INSERT INTO compras VALUES (1,'ana',1,0),(2,'ana',2,86400),(3,'ana',3,10000000);
        CREATE INDEX compras_usuario ON compras(usuario) USING HASH;
        CREATE INDEX compras_producto ON compras(producto_id) USING HASH;
        CREATE TABLE tiendas(id INT, nombre TEXT, ubicacion POINT);
        INSERT INTO tiendas VALUES (1,'A',POINT(0,0)),(2,'B',POINT(0,1));
        CREATE INDEX geo ON tiendas(ubicacion) USING RTREE;
        CREATE TABLE stock(tienda_id INT, producto_id INT, unidades INT);
        INSERT INTO stock VALUES (1,1,0),(2,1,3);
        """
        r = cliente.post("/sql", json={"sql": sql})
        assert r.status_code == 200, r.text
        for pesos, esperado in [("1,0,0", 2), ("0,1,0", 3), ("0,0,1", 3)]:
            filas = cliente.get("/recomendaciones/1", params={"pesos": pesos, "vector_imagen": "sift",
                                                              "peso_categoria": 0}).json()
            assert filas[0]["id"] == esperado
            assert filas[0]["puntaje"] == 1
            assert set(filas[0]["senales"]) == {"texto", "imagen", "compras"}
            assert all(f["id"] != 1 for f in filas)
        # El producto 3 lo compró la misma persona 115 días después: fuera de la ventana de 30 días.
        solo_compras = cliente.get("/recomendaciones/1?pesos=1,0,0&peso_categoria=0&vector_imagen=sift").json()
        assert [f["id"] for f in solo_compras] == [2]
        assert cliente.get("/recomendaciones/1?pesos=0,0,0").status_code == 422
        cnn = cliente.get("/recomendaciones/1?pesos=0,1,0&vector_imagen=mobilenet")
        assert cnn.status_code == 200, cnn.text
        assert otra_peticion == [200, "respondió"]
        assert cnn.json()[0]["id"] == 3
        (tmp_path / "b").unlink()
        # Una imagen que falta se omite: el resto del catálogo sigue recomendándose.
        sin_b = cliente.get("/recomendaciones/1?pesos=0,1,0&vector_imagen=mobilenet")
        assert sin_b.status_code == 200, sin_b.text
        assert [f["id"] for f in sin_b.json()] == [3]
        # Si el producto consultado no tiene vector, quedan las señales de compras y texto.
        sin_vector = cliente.get("/recomendaciones/2?vector_imagen=mobilenet")
        assert sin_vector.status_code == 200, sin_vector.text
        assert all(f["senales"]["imagen"] == 0 for f in sin_vector.json())
        # Sin el modelo, la representación MobileNet no está disponible.
        def sin_modelo(tipo, nombre):
            raise FileNotFoundError("Falta MobileNet. Ejecute python -m engine.features.image.mobilenet")
        monkeypatch.setattr("tienda.indice_imagen.extractor_for", sin_modelo)
        assert cliente.get("/recomendaciones/1?vector_imagen=mobilenet").status_code == 503
        # Sin pedir una representación, se usa SIFT cuando falta el modelo.
        por_defecto = cliente.get("/recomendaciones/1?pesos=0,1,0&peso_categoria=0")
        assert por_defecto.status_code == 200, por_defecto.text
        assert [f["id"] for f in por_defecto.json()] == [3]
        # La indisponibilidad de una representación no altera el índice SIFT.
        assert cliente.get("/recomendaciones/1?vector_imagen=sift").status_code == 200
        assert cliente.get("/recomendaciones/1?peso_categoria=-1").status_code == 422
        assert cliente.get("/recomendaciones/1?vector_imagen=desconocido").status_code == 422
        assert cliente.get("/recomendaciones/999").status_code == 404
        assert cliente.get("/productos/1?lat=0&lon=0").json()["tienda_cercana"]["id"] == 2
        assert [t["id"] for t in cliente.get("/tiendas/cercanas?lat=0&lon=0&radio=100").json()] == [1]
        filas = cliente.get("/catalogo?q=racing&categoria=games&precio_min=20").json()
        assert [f["id"] for f in filas] == [3]


def test_rrf_no_depende_de_la_escala():
    # BM25 sin tope frente a cosenos juntos: con RRF solo cuenta la posición.
    senales = {"texto": {1: 900.0, 2: 3.0, 3: 2.0}, "imagen": {3: 0.91, 2: 0.90, 1: 0.10}}
    filas = fusionar(0, senales, {"texto": 1, "imagen": 1})
    assert [f["id"] for f in filas] == [1, 3, 2]
    maximo = fusionar(0, senales, {"texto": 1, "imagen": 1}, metodo="max")
    assert maximo[0]["id"] == 1 and maximo[0]["puntaje"] > 0.5


def test_rrf_empates_por_id_y_bono_de_categoria():
    senales = {"compras": {7: 1, 4: 1, 9: 2}, "categoria": {7: 1}}
    filas = fusionar(0, senales, {"compras": 1, "categoria": 0})
    assert [f["id"] for f in filas] == [9, 4, 7]  # empate 4 y 7: primero el id menor
    filas = fusionar(0, senales, {"compras": 1, "categoria": 0.25})
    assert [f["id"] for f in filas][:2] == [7, 9]  # el bono suma sin posición
    assert filas[1]["senales"]["categoria"] == 0


def test_compras_solo_usuarios_de_2_a_20(tmp_path):
    from tienda.amazon import compras
    resenas = tmp_path / "r.jsonl.gz"
    lineas = [{"user_id": "uno", "parent_asin": "A", "verified_purchase": True, "timestamp": 1000}]
    lineas += [{"user_id": "dos", "parent_asin": a, "verified_purchase": True, "timestamp": 2000} for a in "AB"]
    lineas += [{"user_id": "muchos", "parent_asin": f"P{i}", "verified_purchase": True, "timestamp": 3000}
               for i in range(21)]
    lineas += [{"user_id": "dos", "parent_asin": "C", "verified_purchase": False, "timestamp": 2000}]
    with gzip.open(resenas, "wt", encoding="utf-8") as f:
        f.writelines(json.dumps(x) + "\n" for x in lineas)
    productos = [{"asin": a, "id": i} for i, a in enumerate(["A", "B", "C"] + [f"P{i}" for i in range(21)], 1)]
    filas = compras(resenas, productos)
    assert {(f["usuario"], f["producto_id"]) for f in filas} == {("dos", 1), ("dos", 2)}
    assert all(f["fecha"] == 2 for f in filas)  # milisegundos -> segundos
