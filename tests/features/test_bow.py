"""Bag of Visual/Audio Words con las fórmulas de la clase 11."""

import numpy as np
import pytest

from engine.features.bow import BagOfWords, idf_from, sample_descriptors, tf_idf
from engine.features.image.bovw import BoVWExtractor


def blobs(seed, centers, per_file=40, files=6):
    """Archivos cuyos descriptores salen de algunos de los centros dados."""
    rng = np.random.default_rng(seed)
    result = []
    for i in range(files):
        chosen = [centers[(i + j) % len(centers)] for j in range(2)]
        result.append(np.concatenate([c + rng.normal(scale=0.05, size=(per_file, len(c))) for c in chosen]))
    return result


CENTERS = [np.array(c, dtype=float) for c in ([0, 0], [5, 0], [0, 5], [5, 5])]


class TestFormulas:
    def test_idf_is_log10_of_n_over_df(self):
        idf = idf_from([np.array([3, 0, 1]), np.array([1, 0, 0]), np.array([2, 0, 0]), np.array([1, 1, 0])])
        np.testing.assert_allclose(idf, [0.0, np.log10(4), np.log10(4)])

    def test_tf_idf_uses_one_plus_log_tf_and_l2(self):
        idf = np.array([1.0, 2.0, 0.5])
        vector = tf_idf(np.array([10.0, 1.0, 0.0]), idf)
        expected = np.array([2.0 * 1.0, 1.0 * 2.0, 0.0])
        np.testing.assert_allclose(vector, expected / np.linalg.norm(expected))

    def test_empty_histogram_stays_zero(self):
        assert not tf_idf(np.zeros(3), np.ones(3)).any()

    def test_sample_takes_descriptors_from_every_file(self):
        sets = [np.full((900, 2), 1.0), np.full((100, 2), 2.0), np.empty((0, 2))]
        sample = sample_descriptors(sets, 100, seed=0)
        assert len(sample) == 100
        assert np.count_nonzero(sample[:, 0] == 2.0) == 10


class TestBagOfWords:
    def test_train_finds_one_word_per_cluster(self):
        bow = BagOfWords.train(blobs(0, CENTERS), k=4, seed=1)
        assert bow.k == 4 and bow.documents == 6
        for center in CENTERS:
            assert np.min(np.linalg.norm(bow.centroids - center, axis=1)) < 0.2

    def test_similar_files_get_similar_vectors(self):
        bow = BagOfWords.train(blobs(0, CENTERS), k=4, seed=1)
        a, b, c = (bow.transform(d) for d in blobs(7, CENTERS, files=3))
        same = bow.transform(blobs(8, CENTERS, files=1)[0])
        assert a.shape == (4,)
        assert np.linalg.norm(a) == pytest.approx(1.0)
        assert a @ same > a @ c

    def test_file_without_descriptors_is_the_zero_vector(self):
        bow = BagOfWords.train(blobs(0, CENTERS), k=4, seed=1)
        assert not bow.transform(np.empty((0, 2))).any()

    def test_save_and_load(self, tmp_path):
        bow = BagOfWords.train(blobs(0, CENTERS), k=4, seed=1, kind="image")
        bow.save(tmp_path / "vocab.npz")
        loaded = BagOfWords.load(tmp_path / "vocab.npz")
        np.testing.assert_array_equal(loaded.centroids, bow.centroids)
        np.testing.assert_array_equal(loaded.idf, bow.idf)
        assert (loaded.kind, loaded.documents) == ("image", 6)
        sample = blobs(3, CENTERS, files=1)[0]
        np.testing.assert_array_equal(loaded.transform(sample), bow.transform(sample))

    def test_rejects_invalid_input(self):
        bow = BagOfWords.train(blobs(0, CENTERS), k=4, seed=1)
        with pytest.raises(ValueError):
            bow.histogram(np.zeros((3, 5)))
        with pytest.raises(ValueError):
            BagOfWords(np.zeros((2, 2))).transform(np.zeros((1, 2)))
        with pytest.raises(ValueError):
            BagOfWords.train([np.empty((0, 2))], k=2)


class TestBoVWExtractorWithLocalDescriptors:
    def test_extract_uses_every_sift_keypoint(self, tmp_path):
        rng = np.random.default_rng(0)
        grid = np.indices((160, 160))
        stripes = ((grid[0] // 8) % 2 * 255).astype(np.uint8)
        checker = (((grid[0] // 16 + grid[1] // 16) % 2) * 255).astype(np.uint8)
        circles = ((np.hypot(grid[0] - 80, grid[1] - 80) // 10 % 2) * 255).astype(np.uint8)
        noise = rng.integers(0, 255, (160, 160), dtype=np.uint8)
        images = [stripes, checker, circles, noise]
        extractor = BoVWExtractor(k=16)
        descriptors = [extractor._extract_sift_descriptors(image) for image in images]
        assert len(descriptors[3]) > 1
        BagOfWords.train(descriptors, k=16, seed=0).save(tmp_path / "v.npz")
        extractor.load_codebook(tmp_path / "v.npz")
        vector = extractor.extract(images[3])
        assert vector.shape == (16,)
        assert np.count_nonzero(vector) > 1
