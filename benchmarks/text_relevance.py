"""Juicios exhaustivos por intención editorial, sin consultar los rankings."""


def is_relevant(document, query):
    return document["categoria"] == query["category"] and (
        not query["topic"] or document["tema"] == query["topic"])


def judgments(documents, queries):
    """Qrels positivos dispersos; los pares omitidos tienen relevancia cero."""
    for document in documents:
        for query in queries:
            if is_relevant(document, query):
                yield {"query_id": query["query_id"], "doc_id": document["id"], "relevance": 1}
