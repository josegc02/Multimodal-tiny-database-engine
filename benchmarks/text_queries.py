"""Consultas e intenciones editoriales; independientes del scoring."""

from benchmarks.text_collection import TOPICS


def queries():
    """6 consultas de una palabra y 12 de cada grupo 3 / 5+."""
    rows = []
    for category in dict.fromkeys(topic[0] for topic in TOPICS):
        rows.append({"query_id": f"q{len(rows) + 1:02d}", "text": category,
                     "words": 1, "category": category, "topic": "",
                     "intent": f"Noticias cuyo asunto principal es {category}."})
    for category, topic, short, _ in TOPICS:
        for text in (short, short + " desarrollo proyectos regionales"):
            rows.append({"query_id": f"q{len(rows) + 1:02d}", "text": text,
                         "words": len(text.split()), "category": category, "topic": topic,
                         "intent": f"Noticias centradas en {topic}; no basta una mención secundaria."})
    return rows
