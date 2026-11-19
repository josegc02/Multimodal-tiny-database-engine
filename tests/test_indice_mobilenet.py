import numpy as np
import pytest

from tienda.indice_imagen import ImageIndex


@pytest.fixture(autouse=True)
def modelo_presente(monkeypatch):
    monkeypatch.setattr("tienda.indice_imagen.extractor_for", lambda tipo, nombre: None)


def test_indice_actualiza_catalogo_y_reutiliza_vectores(tmp_path, monkeypatch):
    llamadas = []
    def extraer(tipo, path, nombre):
        llamadas.append(nombre)
        return np.array([1, int(path[-1])], dtype=float)
    monkeypatch.setattr("tienda.indice_imagen.extract_features", extraer)
    filas = []
    for i in (1, 2, 3):
        path = tmp_path / str(i)
        path.write_bytes(b"imagen")
        filas.append({"id": i, "imagen": str(path)})
    indice = ImageIndex(tmp_path / "cache")
    indice.actualizar(filas)
    assert set(indice.buscar(1)) == {1, 2, 3}
    assert llamadas == ["mobilenet"] * 3
    reabierto = ImageIndex(tmp_path / "cache")
    reabierto.actualizar(filas[:2])
    assert set(reabierto.buscar(1)) == {1, 2}
    assert len(llamadas) == 3
    reabierto.actualizar(filas[:2])
    assert len(llamadas) == 3
    (tmp_path / "1").write_bytes(b"imagen modificada")
    reabierto.actualizar(filas[:2])
    assert len(llamadas) == 4


def _catalogo(tmp_path, ids=(1, 2, 3)):
    filas = []
    for i in ids:
        path = tmp_path / str(i)
        path.write_bytes(b"imagen")
        filas.append({"id": i, "imagen": str(path)})
    return filas


def test_una_imagen_ilegible_se_omite(tmp_path, monkeypatch):
    def extraer(tipo, path, nombre):
        if path.endswith("2"):
            raise ValueError("No se puede decodificar")
        return np.array([1, int(path[-1])], dtype=float)
    monkeypatch.setattr("tienda.indice_imagen.extract_features", extraer)
    filas = _catalogo(tmp_path) + [{"id": 4, "imagen": str(tmp_path / "no-existe")}]
    indice = ImageIndex(tmp_path / "cache")
    indice.actualizar(filas)
    assert set(indice.buscar(1)) == {1, 3}
    assert sorted(i for i, _ in indice.omitidos) == [2, 4]


def test_producto_sin_vector_devuelve_senal_vacia(tmp_path, monkeypatch):
    monkeypatch.setattr("tienda.indice_imagen.extract_features",
                        lambda tipo, path, nombre: np.array([1, int(path[-1])], dtype=float))
    indice = ImageIndex(tmp_path / "cache")
    assert indice.buscar(1) == {}  # antes de construir el índice
    indice.actualizar(_catalogo(tmp_path))
    assert indice.buscar(99) == {}


def test_sin_modelo_falla_antes_de_recorrer_el_catalogo(tmp_path, monkeypatch):
    def sin_modelo(tipo, nombre):
        raise FileNotFoundError("Falta MobileNet")
    monkeypatch.setattr("tienda.indice_imagen.extractor_for", sin_modelo)
    with pytest.raises(FileNotFoundError):
        ImageIndex(tmp_path / "cache").actualizar(_catalogo(tmp_path))



def test_vigente_durante_el_intervalo_de_revision(tmp_path, monkeypatch):
    monkeypatch.setattr("tienda.indice_imagen.extract_features",
                        lambda tipo, path, nombre: np.array([1, int(path[-1])], dtype=float))
    reloj = [1000.0]
    monkeypatch.setattr("tienda.indice_imagen.time.monotonic", lambda: reloj[0])
    indice = ImageIndex(tmp_path / "cache")
    assert not indice.vigente()  # sin índice: hay que construirlo
    indice.actualizar(_catalogo(tmp_path))
    assert indice.vigente()
    reloj[0] += ImageIndex.REVISION_S - 1
    assert indice.vigente()
    reloj[0] += 2
    assert not indice.vigente()  # pasó el intervalo: se vuelve a revisar
    indice.actualizar(_catalogo(tmp_path))  # misma firma: no reconstruye, pero cuenta como revisión
    assert indice.vigente()


def test_precalentar_construye_el_indice_al_iniciar(tmp_path, monkeypatch):
    import threading
    from frontend.motor import Motor
    from api.tienda import precalentar
    monkeypatch.setattr("tienda.indice_imagen.extract_features",
                        lambda tipo, path, nombre: np.array([1, int(path[-1])], dtype=float))
    motor = Motor(directorio=str(tmp_path / "datos"), modo_demo=False)
    estado, lock = {"motor": motor}, threading.Lock()
    precalentar(estado, lock).join(timeout=10)
    assert "indice_mobilenet" not in estado  # sin tienda cargada no hace nada
    motor.ejecutar("CREATE TABLE productos (id INT PRIMARY KEY, imagen TEXT)")
    filas = _catalogo(tmp_path)
    motor.ejecutar("INSERT INTO productos VALUES " + ", ".join(f"({f['id']}, '{f['imagen']}')" for f in filas))
    precalentar(estado, lock).join(timeout=10)
    assert estado["indice_mobilenet"].vigente()
    assert set(estado["indice_mobilenet"].buscar(1)) == {1, 2, 3}
    motor.cerrar()
