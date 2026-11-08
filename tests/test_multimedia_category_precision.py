import json

from benchmarks.multimedia_category_precision import category_precision


def test_category_precision_counts_multilabel_hits(tmp_path):
    subset = tmp_path / "coco1k"
    subset.mkdir()
    images = [{"id": i, "file_name": f"{i}.jpg"} for i in range(20)]
    # 0..4 tienen gato, 0 y 10 tienen perro.
    annotations = ([{"image_id": i, "category_id": 1} for i in range(5)]
                   + [{"image_id": i, "category_id": 2} for i in (0, 10)])
    (subset / "instances_subset.json").write_text(json.dumps({
        "images": images, "annotations": annotations,
        "categories": [{"id": 1, "name": "cat"}, {"id": 2, "name": "dog"}]}), encoding="utf-8")
    exact = [f"{i}.jpg" for i in range(1, 11)]   # 4 gatos (1..4)
    found = [f"{i}.jpg" for i in range(10, 20)]  # ningún gato
    rows = [{"size": 1000, "metric": "euclidean", "technique": t, "category": "cat",
             "exact_files": exact, "found_files": exact if t == "IVF" else found} for t in ("IVF", "HNSW")]
    result = {r["technique"]: r["precision_at_10"] for r in category_precision(tmp_path, rows)}
    assert result == {"IVF": 0.4, "HNSW": 0.0, "exacto": 0.4, "azar": 0.25}
