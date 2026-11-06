"""Evaluación por identificadores externos, nunca por scores entre técnicas."""

import math


def relevance_at_k(ids, relevant, k=10):
    if type(k) is not int or k < 1:
        raise ValueError("k debe ser positivo")
    ids = list(ids)
    if len(ids) > k or len(set(ids)) != len(ids):
        raise ValueError("Ranking excede k o contiene IDs duplicados")
    hits = len(set(ids) & set(relevant))
    return {"hits": hits, "returned": len(ids), "relevant": len(relevant),
            "precision": hits / k, "recall": hits / len(relevant) if relevant else None}


def validate_ranking(rows, size, k=10):
    ids = [row[0] for row in rows]
    if len(ids) > k or len(set(ids)) != len(ids) or any(type(i) is not int or not 1 <= i <= size for i in ids):
        raise ValueError("IDs inválidos en ranking")
    if any(not math.isfinite(score) or score < 0 for _, score in rows):
        raise ValueError("Score inválido")
    if rows != sorted(rows, key=lambda row: (-row[1], row[0])):
        raise ValueError("Ranking no está ordenado por score DESC, id ASC")
