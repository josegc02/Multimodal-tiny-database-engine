from __future__ import annotations

from typing import Any, Dict, Generator, List, Optional, Tuple

from engine.storage.record import RID, Schema


class SequentialFile:
    """
    Archivo Secuencial Paginado:
    - Páginas ordenadas por clave primaria.
    - Área auxiliar (overflow) para inserciones intermedias.
    - Reorganización automática cuando el área auxiliar supera el umbral (>30%).
    - Búsqueda binaria sobre páginas principales.
    """

    def __init__(self, filepath: str, schema_def: List[Tuple[Any, ...]], pk_field: str, page_size: int = 4096):
        self.filepath = filepath
        self.schema = Schema(schema_def)
        self.pk_field = pk_field
        self.page_size = page_size
        # TODO: Implementar lógica de páginas ordenadas y overflow
