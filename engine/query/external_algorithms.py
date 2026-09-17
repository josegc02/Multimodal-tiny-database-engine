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
import hashlib
from itertools import islice
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
    row = None  # No retener el último registro de entrada durante las mezclas.
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


@dataclass(frozen=True)
class Aggregate:
    """COUNT(*) usa field=None; los demás agregados requieren un campo."""

    function: str = "count"
    field: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "function", self.function.lower())
        if self.function not in {"count", "sum", "avg", "min", "max"}:
            raise ValueError("Agregado no soportado")
        if self.function != "count" and not self.field:
            raise ValueError("El agregado requiere un campo")


def _fields(fields: str | Sequence[str], *, allow_empty: bool = False) -> tuple[str, ...]:
    result = (fields,) if isinstance(fields, str) else tuple(fields)
    if ((not result and not allow_empty)
            or any(not isinstance(item, str) or not item for item in result)
            or len(set(result)) != len(result)):
        raise ValueError("Se requieren campos válidos y sin repeticiones")
    return result


def _aggregates(fields: tuple[str, ...], aggregates: Mapping[str, Aggregate] | None) -> dict:
    result = dict(aggregates) if aggregates is not None else {"count": Aggregate()}
    if not result or any(
        not isinstance(alias, str) or not alias or alias in fields or not isinstance(spec, Aggregate)
        for alias, spec in result.items()
    ):
        raise ValueError("Los agregados necesitan aliases únicos que no sean campos de agrupación")
    return result


def _new_state(specs: Mapping[str, Aggregate]) -> list:
    # [cantidad no nula, acumulado]; una cantidad fija de valores por grupo.
    return [[0, None] for _ in specs]


def _accumulate(state: list, row: Row, specs: Mapping[str, Aggregate]) -> None:
    for slot, spec in zip(state, specs.values()):
        value = 1 if spec.field is None else row[spec.field]
        if value is None:
            continue
        slot[0] += 1
        if spec.function == "count":
            continue
        if spec.function in {"sum", "avg"}:
            if type(value) not in (int, float):
                raise TypeError("SUM y AVG requieren valores numéricos")
            if type(value) is float and not math.isfinite(value):
                raise ValueError("SUM y AVG requieren valores finitos")
            slot[1] = value if slot[1] is None else slot[1] + value
        elif slot[1] is None:
            slot[1] = value
        elif spec.function == "min":
            slot[1] = min(slot[1], value)
        else:
            slot[1] = max(slot[1], value)


def _group_result(key: tuple, state: list, fields: tuple, specs: Mapping[str, Aggregate]) -> dict:
    result = dict(zip(fields, key))
    for (alias, spec), (count, value) in zip(specs.items(), state):
        result[alias] = count if spec.function == "count" else (
            value / count if spec.function == "avg" and count else value
        )
    return result


def _ordered_groups(rows: Iterable[Row], fields: tuple, specs: dict) -> Iterator[Row]:
    current = None
    state = None
    for row in rows:
        key = _key(row, fields)
        if state is None or key != current:
            if state is not None:
                yield _group_result(current, state, fields, specs)
            current = key
            state = _new_state(specs)
        _accumulate(state, row, specs)
    if state is not None:
        yield _group_result(current, state, fields, specs)
    elif not fields:
        yield _group_result((), _new_state(specs), fields, specs)


def streaming_group_by(
    rows: Iterable[Row], group_by: str | Sequence[str],
    aggregates: Mapping[str, Aggregate] | None = None,
) -> Iterator[Row]:
    """Agrupa con un solo estado si la fuente garantiza claves contiguas.

    Se usa para recorridos de índices ordenados y para el fallback por sorting.
    None forma un grupo; COUNT(campo), SUM, AVG, MIN y MAX ignoran valores None.
    """
    fields = _fields(group_by, allow_empty=True)
    yield from _ordered_groups(rows, fields, _aggregates(fields, aggregates))


def _partition_id(key: tuple, fanout: int, depth: int) -> int:
    # hp estable y distinto por nivel. La tabla de construcción usa hash(tuple)
    # de Python como h2 y compara las claves completas al resolver colisiones.
    canonical = []
    for value in key:
        if value is None:
            canonical.append(("null",))
        elif type(value) in (int, float):
            numerator, denominator = value.as_integer_ratio() if type(value) is float else (value, 1)
            canonical.append(("n", numerator, denominator))
        else:
            canonical.append(("s", value))
    data = repr((depth, canonical)).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "big") % fanout


def _partition(
    rows: Iterable[Row], fields: tuple, ws: _Workspace, depth: int, *, skip_nulls: bool = False,
) -> list[_Run]:
    paths = [ws.path() for _ in range(ws.config.fan_in)]
    counts = [0] * len(paths)
    with ExitStack() as stack:
        writers = [stack.enter_context(ws.open(path, "wb")) for path in paths]
        for row in rows:
            key = _key(row, fields)
            if skip_nulls and any(value is None for value in key):
                continue
            position = _partition_id(key, len(paths), depth)
            write_record(writers[position], row)
            counts[position] += 1
            ws.stats.records_written += 1
            ws.observe(1)
    ws.stats.partitions += len(paths)
    return [_Run(path, count) for path, count in zip(paths, counts)]


def _group_partition(run: _Run, fields: tuple, specs: dict, ws: _Workspace, depth: int) -> Iterator[Row]:
    table = {}
    overflow = False
    with closing(ws.read(run)) as rows:
        for row in rows:
            key = _key(row, fields)
            if key not in table:
                if len(table) == ws.config.hash_capacity:
                    overflow = True
                    break
                table[key] = _new_state(specs)
            _accumulate(table[key], row, specs)
            ws.observe(len(table) + 1)
    if not overflow:
        for key, state in table.items():
            yield _group_result(key, state, fields, specs)
        return
    table.clear()
    row = None  # Liberar la entrada que provocó overflow antes de recursar.

    if depth >= ws.config.max_partition_depth:
        ws.stats.skew_fallbacks += 1
        with closing(ws.read(run)) as rows, closing(_sort(rows, _order_keys(fields), ws)) as ordered:
            yield from _ordered_groups(ordered, fields, specs)
        return

    ws.stats.repartitions += 1
    with closing(ws.read(run)) as rows:
        children = _partition(rows, fields, ws, depth + 1)
    run.path.unlink()
    no_progress = max(child.count for child in children) == run.count
    for child in children:
        if not child.count:
            child.path.unlink()
            continue
        if no_progress:
            ws.stats.skew_fallbacks += 1
            with closing(ws.read(child)) as rows, closing(_sort(rows, _order_keys(fields), ws)) as ordered:
                yield from _ordered_groups(ordered, fields, specs)
        else:
            yield from _group_partition(child, fields, specs, ws, depth + 1)
        child.path.unlink(missing_ok=True)


def external_hash_group_by(
    rows: Iterable[Row], group_by: str | Sequence[str],
    aggregates: Mapping[str, Aggregate] | None = None, *,
    config: BufferConfig | None = None, stats: ExecutionStats | None = None,
) -> Iterator[Row]:
    """GROUP BY: B-1 particiones y tablas de hasta (B-2)*R grupos en memoria.

    Reparticiona si hay demasiados grupos. Ante skew sin progreso o al alcanzar
    max_partition_depth, usa sorting externo y un acumulador por grupo. La salida
    no promete orden. Sin campos de agrupación produce un agregado global.
    """
    config = config or BufferConfig()
    stats = stats if stats is not None else ExecutionStats()
    fields = _fields(group_by, allow_empty=True)
    specs = _aggregates(fields, aggregates)
    if not fields:
        stats.peak_buffered_records = max(stats.peak_buffered_records, 2)
        yield from _ordered_groups(rows, fields, specs)
        return
    with tempfile.TemporaryDirectory(prefix="external-group-", dir=config.temp_dir) as directory:
        ws = _Workspace(directory, config, stats)
        partitions = _partition(rows, fields, ws, 0)
        for run in partitions:
            if run.count:
                yield from _group_partition(run, fields, specs, ws, 0)
            run.path.unlink(missing_ok=True)


def _probe_join(table: dict, probe: _Run, fields: tuple, swapped: bool, ws: _Workspace):
    with closing(ws.read(probe)) as rows:
        for row in rows:
            for match in table.get(_key(row, fields), ()):
                # Mantener orientación izquierda/derecha aunque se construya S.
                yield (row, match) if swapped else (match, row)


def _build_join_table(rows: Iterable[Row], fields: tuple, ws: _Workspace) -> dict:
    table = {}
    count = 0
    for row in rows:
        table.setdefault(_key(row, fields), []).append(row)
        count += 1
        ws.observe(count + 1)  # Construcción + registro corriente del probe.
    return table


def _block_join(build: _Run, probe: _Run, build_fields: tuple, probe_fields: tuple,
                swapped: bool, ws: _Workspace):
    """Fallback acotado para skew: hash por bloques y relectura del probe."""
    ws.stats.skew_fallbacks += 1
    with closing(ws.read(build)) as rows:
        while True:
            table = _build_join_table(islice(rows, ws.config.hash_capacity), build_fields, ws)
            if not table:
                break
            yield from _probe_join(table, probe, probe_fields, swapped, ws)
            table.clear()


def _join_partition(left: _Run, right: _Run, left_fields: tuple, right_fields: tuple,
                    ws: _Workspace, depth: int):
    if not left.count or not right.count:
        return
    swapped = right.count < left.count
    build, probe = (right, left) if swapped else (left, right)
    build_fields, probe_fields = (right_fields, left_fields) if swapped else (left_fields, right_fields)
    if build.count <= ws.config.hash_capacity:
        with closing(ws.read(build)) as rows:
            table = _build_join_table(rows, build_fields, ws)
        yield from _probe_join(table, probe, probe_fields, swapped, ws)
        return
    if depth >= ws.config.max_partition_depth:
        yield from _block_join(build, probe, build_fields, probe_fields, swapped, ws)
        return

    ws.stats.repartitions += 1
    with closing(ws.read(left)) as rows:
        left_parts = _partition(rows, left_fields, ws, depth + 1)
    with closing(ws.read(right)) as rows:
        right_parts = _partition(rows, right_fields, ws, depth + 1)
    left.path.unlink()
    right.path.unlink()
    for lpart, rpart in zip(left_parts, right_parts):
        # Si no se redujo el lado de construcción, más hashing no garantiza
        # progreso (por ejemplo, una sola clave repetida en ambas relaciones).
        if min(lpart.count, rpart.count) >= build.count:
            swap_child = rpart.count < lpart.count
            bpart, ppart = (rpart, lpart) if swap_child else (lpart, rpart)
            bfields, pfields = (right_fields, left_fields) if swap_child else (left_fields, right_fields)
            yield from _block_join(bpart, ppart, bfields, pfields, swap_child, ws)
        else:
            yield from _join_partition(lpart, rpart, left_fields, right_fields, ws, depth + 1)
        lpart.path.unlink(missing_ok=True)
        rpart.path.unlink(missing_ok=True)


def external_hash_join(
    left_rows: Iterable[Row], right_rows: Iterable[Row],
    left_on: str | Sequence[str], right_on: str | Sequence[str], *,
    config: BufferConfig | None = None, stats: ExecutionStats | None = None,
) -> Iterator[tuple[Row, Row]]:
    """INNER equijoin Grace: particiona ambas fuentes con la misma hp.

    Construye una tabla sobre la partición menor y sondea con la otra. Cuenta
    registros, no claves distintas, al limitar el buffer de construcción. Las
    claves duplicadas producen todas las combinaciones; NULL no coincide con NULL.
    Si hay skew usa bloques de tamaño (B-2)*R y relee la partición opuesta.
    Devuelve pares (registro_izquierdo, registro_derecho) para no perder columnas
    homónimas. No materializa el resultado ni garantiza un orden de salida.
    """
    config = config or BufferConfig()
    stats = stats if stats is not None else ExecutionStats()
    left_fields, right_fields = _fields(left_on), _fields(right_on)
    if len(left_fields) != len(right_fields):
        raise ValueError("JOIN requiere igual cantidad de campos en ambos lados")
    with tempfile.TemporaryDirectory(prefix="external-join-", dir=config.temp_dir) as directory:
        ws = _Workspace(directory, config, stats)
        left_parts = _partition(left_rows, left_fields, ws, 0, skip_nulls=True)
        right_parts = _partition(right_rows, right_fields, ws, 0, skip_nulls=True)
        for left, right in zip(left_parts, right_parts):
            yield from _join_partition(left, right, left_fields, right_fields, ws, 0)
            left.path.unlink(missing_ok=True)
            right.path.unlink(missing_ok=True)
