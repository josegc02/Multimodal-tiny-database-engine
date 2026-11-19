import numpy as np
import pytest

from engine.features.image.mobilenet import MODEL, MobileNetExtractor


def test_modelo_ausente_indica_como_instalar(tmp_path):
    with pytest.raises(FileNotFoundError, match="python -m"):
        MobileNetExtractor(tmp_path / "ausente.onnx")


@pytest.mark.skipif(not MODEL.exists(), reason="Requiere descargar el modelo ONNX")
def test_embedding_real_normalizado_y_repetible(tmp_path):
    import cv2
    imagen = tmp_path / "foto.png"
    cv2.imwrite(str(imagen), np.full((300, 400, 3), 120, dtype=np.uint8))
    extractor = MobileNetExtractor()
    vector = extractor(str(imagen))
    assert vector.shape == (1280,)
    assert np.isfinite(vector).all()
    assert np.linalg.norm(vector) == pytest.approx(1)
    np.testing.assert_allclose(vector, extractor(str(imagen)))
