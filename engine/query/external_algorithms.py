"""Operadores externos con temporales privados y buffers de registros limitados.

El modelo de la PPT se simula con B páginas de R registros cada una: no es una
cuota de bytes del proceso Python. La entrada y la salida son iterables; quien
consuma parcialmente un resultado debe cerrar su generador (close()). Los
temporales usan un formato binario explícito con struct (ver _temp_records).
"""

from __future__ import annotations

from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
import heapq
import math
from pathlib import Path
import tempfile
from typing import Any, Iterable, Iterator, Mapping, Sequence

from engine.query._temp_records import read_header, read_record, write_header, write_record

Row = Mapping[str, Any]


@dataclass(frozen=True)
class BufferConfig:
    buffer_pages: int = 8
    records_per_page: int = 128
    max_partition_depth: int = 8
    temp_dir: str | None = None

    def __post_init__(self):
        if type(self.buffer_pages) is not int or self.buffer_pages < 3:
            raise ValueError("Se necesitan al menos 3 páginas de buffer")
        if type(self.records_per_page) is not int or self.records_per_page < 1:
            raise ValueError("records_per_page debe ser un entero positivo")
        if type(self.max_partition_depth) is not int or self.max_partition_depth < 0:
            raise ValueError("max_partition_depth debe ser un entero no negativo")

    @property
    def capacity(self) -> int:
        return self.buffer_pages * self.records_per_page

    @property
    def fan_in(self) -> int:
        return self.buffer_pages - 1

    @property
    def hash_capacity(self) -> int:
        # Reservar una página para lectura y otra para salida.
        return (self.buffer_pages - 2) * self.records_per_page


@dataclass
class ExecutionStats:
    """Contadores de registros lógicos; no incluyen objetos/metadatos de Python."""

    initial_runs: int = 0
    merge_passes: int = 0
    partitions: int = 0
    repartitions: int = 0
    skew_fallbacks: int = 0
    records_written: int = 0
    records_read: int = 0
    peak_buffered_records: int = 0
    peak_open_files: int = 0
    index_probes: int = 0


@dataclass(frozen=True)
class OrderKey:
    field: str
    descending: bool = False
    nulls_first: bool = False


def _order_keys(order_by: str | Sequence[str | OrderKey]) -> tuple[OrderKey, ...]:
    if isinstance(order_by, str):
        order_by = (order_by,)
    result = tuple(OrderKey(item) if isinstance(item, str) else item for item in order_by)
    if not result or any(not isinstance(item, OrderKey) or not item.field for item in result):
        raise ValueError("ORDER BY requiere al menos un campo válido")
    return result


def _key(row: Row, fields: Sequence[str]) -> tuple:
    values = tuple(row[field] for field in fields)
    for value in values:
        if value is not None and type(value) not in (int, float, str):
            raise TypeError("Las claves deben ser int, float finitos, str o None")
        if type(value) is float and not math.isfinite(value):
            raise ValueError("No se permiten claves NaN o infinitas")
    return values


class _SortKey:
    def __init__(self, row: Row, order: tuple[OrderKey, ...]):
        self.values = _key(row, tuple(item.field for item in order))
        self.order = order

    def __eq__(self, other):
        return self.values == other.values

    def __lt__(self, other):
        for left, right, rule in zip(self.values, other.values, self.order):
            if left == right:
                continue
            if left is None:
                return rule.nulls_first
            if right is None:
                return not rule.nulls_first
            return left > right if rule.descending else left < right
        return False


@dataclass(frozen=True)
class _Run:
    path: Path
    count: int


class _Workspace:
    def __init__(self, directory: str, config: BufferConfig, stats: ExecutionStats):
        self.directory = Path(directory)
        self.config = config
        self.stats = stats
        self._counter = 0
        self._open_files = 0

    def path(self) -> Path:
        self._counter += 1
        return self.directory / f"part-{self._counter}.bin"

    def observe(self, records: int) -> None:
        if records > self.config.capacity:
            raise RuntimeError("Se excedió el buffer lógico de registros")
        self.stats.peak_buffered_records = max(self.stats.peak_buffered_records, records)

    @contextmanager
    def open(self, path: Path, mode: str):
        with path.open(mode) as fh:
            self._open_files += 1
            self.stats.peak_open_files = max(self.stats.peak_open_files, self._open_files)
            try:
                if mode == "wb":
                    write_header(fh)
                else:
                    read_header(fh)
                yield fh
            finally:
                self._open_files -= 1

    def read(self, run: _Run) -> Iterator[Row]:
        with self.open(run.path, "rb") as fh:
            for _ in range(run.count):
                row = read_record(fh)
                self.stats.records_read += 1
                yield row

    def write(self, rows: Iterable[Row]) -> _Run:
        path = self.path()
        count = 0
        with self.open(path, "wb") as fh:
            for row in rows:
                write_record(fh, row)
                count += 1
                self.stats.records_written += 1
        return _Run(path, count)


def _merge(runs: Sequence[_Run], order: tuple[OrderKey, ...], ws: _Workspace) -> Iterator[Row]:
    # Un registro corriente por entrada; el resto permanece en los archivos.
    # El número de entradas nunca supera B-1; queda un descriptor para la salida.
    with ExitStack() as stack:
        readers = [stack.enter_context(closing(ws.read(run))) for run in runs]
        heap = []
        for position, reader in enumerate(readers):
            row = next(reader, None)
            if row is not None:
                heapq.heappush(heap, (_SortKey(row, order), position, row))
        while heap:
            ws.observe(len(heap))
            _, position, row = heapq.heappop(heap)
            yield row
            row = next(readers[position], None)
            if row is not None:
                heapq.heappush(heap, (_SortKey(row, order), position, row))


def _sort(rows: Iterable[Row], order: tuple[OrderKey, ...], ws: _Workspace) -> Iterator[Row]:
    runs = []
    chunk = []
    for row in rows:
        # Tomar una copia: algunos productores reutilizan un mismo diccionario.
        chunk.append(dict(row))
        ws.observe(len(chunk))
        if len(chunk) == ws.config.capacity:
            chunk.sort(key=lambda item: _SortKey(item, order))
            runs.append(ws.write(chunk))
            chunk.clear()
    if chunk:
        chunk.sort(key=lambda item: _SortKey(item, order))
        runs.append(ws.write(chunk))
        chunk.clear()
    ws.stats.initial_runs += len(runs)

    while len(runs) > 1:
        merged = []
        for start in range(0, len(runs), ws.config.fan_in):
            group = runs[start:start + ws.config.fan_in]
            if len(group) == 1:
                merged.append(group[0])
                continue
            with closing(_merge(group, order, ws)) as stream:
                merged.append(ws.write(stream))
            for run in group:
                run.path.unlink()
        runs = merged
        ws.stats.merge_passes += 1
    if runs:
        yield from ws.read(runs[0])
        runs[0].path.unlink()


def external_sort(
    rows: Iterable[Row], order_by: str | Sequence[str | OrderKey], *,
    config: BufferConfig | None = None, stats: ExecutionStats | None = None,
) -> Iterator[Row]:
    """ORDER BY estable: runs de B*R registros y merge de como máximo B-1 runs.

    Admite varias columnas, ASC/DESC por columna y posición explícita de NULL.
    Realiza tantas pasadas como sean necesarias y no materializa la salida.
    """
    config = config or BufferConfig()
    stats = stats if stats is not None else ExecutionStats()
    order = _order_keys(order_by)
    with tempfile.TemporaryDirectory(prefix="external-sort-", dir=config.temp_dir) as directory:
        yield from _sort(rows, order, _Workspace(directory, config, stats))
