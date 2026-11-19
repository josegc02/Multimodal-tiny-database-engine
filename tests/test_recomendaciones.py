import numpy as np
from fastapi.testclient import TestClient

from api.main import create_app
from tienda.recomendaciones import fusionar


def test_top_diez_y_desempate():
    senales = {"compras": {i: 1 for i in range(20)}}
    filas = fusionar(0, senales, {"compras": 1})
    assert [f["id"] for f in filas] == list(range(1, 11))


def test_tienda_http(tmp_path, monkeypatch):
    vectores = {"a": [1, 0], "b": [0, 1], "c": [1, 0.1]}
    monkeypatch.setattr("engine.storage.media_store.extract_features",
                        lambda tipo, ruta: np.array(vectores[ruta]))
    with TestClient(create_app(str(tmp_path), llm=None)) as cliente:
        sql = """
        CREATE TABLE productos(id INT PRIMARY KEY, descripcion TEXT, imagen IMAGE, precio FLOAT, categoria TEXT);
        INSERT INTO productos VALUES (1,'racing console','a',10,'games'),(2,'sports','b',20,'games'),
                                     (3,'racing console','c',30,'games');
        CREATE INDEX img ON productos(imagen) USING HNSW WITH (METRIC=cosine);
        CREATE INDEX txt ON productos(descripcion) USING SPIMI WITH (LANGUAGE='en');
        CREATE TABLE compras(id INT, usuario VARCHAR(20), producto_id INT);
        INSERT INTO compras VALUES (1,'ana',1),(2,'ana',2);
        CREATE TABLE tiendas(id INT, nombre TEXT, ubicacion POINT);
        INSERT INTO tiendas VALUES (1,'A',POINT(0,0)),(2,'B',POINT(0,1));
        CREATE INDEX geo ON tiendas(ubicacion) USING RTREE;
        CREATE TABLE stock(tienda_id INT, producto_id INT, unidades INT);
        INSERT INTO stock VALUES (1,1,0),(2,1,3);
        """
        r = cliente.post("/sql", json={"sql": sql})
        assert r.status_code == 200, r.text
        for pesos, esperado in [("1,0,0", 2), ("0,1,0", 3), ("0,0,1", 3)]:
            filas = cliente.get("/recomendaciones/1", params={"pesos": pesos}).json()
            assert filas[0]["id"] == esperado
            assert filas[0]["puntaje"] == 1
            assert set(filas[0]["senales"]) == {"texto", "imagen", "compras"}
            assert all(f["id"] != 1 for f in filas)
        assert cliente.get("/recomendaciones/1?pesos=0,0,0").status_code == 422
        assert cliente.get("/recomendaciones/999").status_code == 404
        assert cliente.get("/productos/1?lat=0&lon=0").json()["tienda_cercana"]["id"] == 2
        assert [t["id"] for t in cliente.get("/tiendas/cercanas?lat=0&lon=0&radio=100").json()] == [1]
        filas = cliente.get("/catalogo?q=racing&categoria=games&precio_min=20").json()
        assert [f["id"] for f in filas] == [3]
