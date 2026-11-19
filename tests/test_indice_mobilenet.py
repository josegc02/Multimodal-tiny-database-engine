import numpy as np

from tienda.indice_imagen import ImageIndex


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
