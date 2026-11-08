"""El script de entrenamiento usa descriptores locales y guarda un vocabulario con IDF."""

import numpy as np

from engine.features.bow import BagOfWords
from engine.features.registry import vocabulary_path
from scripts.train_codebook import train_codebook


def test_trains_an_image_vocabulary_from_local_descriptors(tmp_path):
    import cv2

    rng = np.random.default_rng(0)
    for i in range(4):
        cv2.imwrite(str(tmp_path / f"img{i}.png"), rng.integers(0, 255, (160, 160), dtype=np.uint8))
    (tmp_path / "notas.txt").write_text("no es una imagen")
    output = tmp_path / "vocab.npz"
    bow = train_codebook("image", tmp_path, k=16, sample=5000, output=output, workers=2)
    loaded = BagOfWords.load(output)
    assert (loaded.k, loaded.dimension, loaded.documents, loaded.kind) == (16, 128, 4, "image")
    np.testing.assert_array_equal(loaded.idf, bow.idf)


def test_trains_an_audio_vocabulary_from_mfcc_windows(tmp_path):
    import soundfile

    rate = 22050
    times = np.arange(rate) / rate
    for i, frequency in enumerate((200, 400, 800, 1600)):
        soundfile.write(str(tmp_path / f"tono{i}.wav"), 0.5 * np.sin(2 * np.pi * frequency * times), rate)
    bow = train_codebook("audio", tmp_path, k=8, output=tmp_path / "audio.npz", workers=2)
    assert (bow.dimension, bow.documents) == (13, 4)


def test_committed_vocabularies():
    for kind, k, dimension in (("image", 1024, 128), ("audio", 256, 13)):
        bow = BagOfWords.load(vocabulary_path(kind))
        assert (bow.k, bow.dimension, bow.kind) == (k, dimension, kind)
        assert np.all(bow.idf > 0)


def test_image_vocabulary_matches_the_sift_scale():
    # OpenCV entrega descriptores SIFT con norma L2 cercana a 512. Un vocabulario entrenado
    # con descriptores normalizados (por ejemplo, RootSIFT, de norma 1) no serviría con
    # los que extrae el motor, y todo caería en las mismas pocas palabras sin dar error.
    bow = BagOfWords.load(vocabulary_path("image"))
    norms = np.linalg.norm(bow.centroids, axis=1)
    assert np.all((norms > 100) & (norms < 600))
