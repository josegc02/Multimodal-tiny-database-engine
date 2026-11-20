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

