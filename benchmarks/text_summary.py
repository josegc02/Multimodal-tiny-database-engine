"""Agregación por repetición primero: evita confundir consultas con réplicas."""

from benchmarks.text_output import summarize, write_csv

BUILD_METRICS = ("load_seconds", "build_seconds", "ready_seconds", "index_bytes", "total_bytes",
                 "rss_initial_bytes", "rss_peak_bytes", "client_peak_bytes")
QUERY_METRICS = ("query_seconds", "precision", "recall", "postings_read", "pages_read")


def export_summaries(output, runs, queries):
    build = summarize(runs, ("size", "technique"), BUILD_METRICS)
    # Promedio macro por query, dentro de cada longitud y repetición.
    groups = summarize(queries, ("size", "technique", "repetition", "words"), QUERY_METRICS)
    query = summarize(groups, ("size", "technique", "words"), QUERY_METRICS)
    write_csv(output / "build_summary.csv", build)
    write_csv(output / "query_group_runs.csv", groups)
    write_csv(output / "query_summary.csv", query)
