import pytest

from engine.features import registry


def test_alternar_imagen_no_reemplaza_extractor_predeterminado(monkeypatch):
    sift = lambda path: [1, 0]
    cnn = lambda path: [0, 1]
    monkeypatch.setattr(registry, "_extractors", {"image": sift})
    monkeypatch.setattr("engine.features.image.mobilenet.MobileNetExtractor", lambda: cnn)
    assert registry.extractor_for("image", "mobilenet") is cnn
    assert registry.extractor_for("image") is sift
    assert registry.extractor_for("image", "sift") is sift
    with pytest.raises(ValueError):
        registry.extractor_for("image", "desconocido")
    with pytest.raises(ValueError):
        registry.extractor_for("audio", "sift")
