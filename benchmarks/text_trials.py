"""Pasada caliente y mediciones por consulta, fuera del cálculo de relevancia."""

from benchmarks.text_measure import timed
from benchmarks.text_metrics import relevance_at_k, validate_ranking


def query_trials(adapter, queries, relevant, size):
    for query in queries:
        adapter.search(query["text"])
    samples, rankings = [], []
    for query in queries:
        elapsed, rows = timed(lambda: adapter.search(query["text"]))
        validate_ranking(rows, size)
        result = {"query_id": query["query_id"], "words": query["words"], "query_seconds": elapsed,
                  **relevance_at_k([doc_id for doc_id, _ in rows], relevant[query["query_id"]]),
                  **adapter.counters()}
        samples.append(result)
        for position, (doc_id, score) in enumerate(rows, 1):
            rankings.append({"query_id": query["query_id"], "rank": position,
                             "doc_id": doc_id, "score": score,
                             "relevant": int(doc_id in relevant[query["query_id"]])})
    return samples, rankings
