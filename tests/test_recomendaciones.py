import threading
import numpy as np
from fastapi.testclient import TestClient

from api.main import create_app
from tienda.recomendaciones import fusionar


def test_top_diez_y_desempate():
    senales = {"compras": {i: 1 for i in range(20)}}
    filas = fusionar(0, senales, {"compras": 1})
    assert [f["id"] for f in filas] == list(range(1, 11))


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
        # La indisponibilidad de una representación no altera el índice SIFT.
        assert cliente.get("/recomendaciones/1?vector_imagen=sift").status_code == 200
        assert cliente.get("/recomendaciones/1?vector_imagen=desconocido").status_code == 422
        assert cliente.get("/recomendaciones/999").status_code == 404
        assert cliente.get("/productos/1?lat=0&lon=0").json()["tienda_cercana"]["id"] == 2
        assert [t["id"] for t in cliente.get("/tiendas/cercanas?lat=0&lon=0&radio=100").json()] == [1]
        filas = cliente.get("/catalogo?q=racing&categoria=games&precio_min=20").json()
        assert [f["id"] for f in filas] == [3]
