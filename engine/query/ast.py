"""AST inmutable del dialecto SQL. No consulta catálogos ni ejecuta operaciones."""

from __future__ import annotations

from dataclasses import dataclass, fields


class Node:
    def to_dict(self) -> dict:
        """Representación serializable para inspección y la futura UI de planes."""
        def convert(value):
            if isinstance(value, Node):
                return value.to_dict()
            if isinstance(value, tuple):
                return [convert(item) for item in value]
            return value
        return {"type": type(self).__name__, **{f.name: convert(getattr(self, f.name)) for f in fields(self)}}


class Expression(Node):
    pass


@dataclass(frozen=True)
class Literal(Expression):
    value: int | float | str | bool | None


@dataclass(frozen=True)
class ColumnRef(Expression):
    name: str
    table: str | None = None


@dataclass(frozen=True)
class Star(Expression):
    table: str | None = None


@dataclass(frozen=True)
class UnaryOp(Expression):
    operator: str
    operand: Expression


@dataclass(frozen=True)
class BinaryOp(Expression):
    operator: str
    left: Expression
    right: Expression


@dataclass(frozen=True)
class IsNull(Expression):
    expression: Expression
    negated: bool = False


@dataclass(frozen=True)
class Between(Expression):
    expression: Expression
    lower: Expression
    upper: Expression
    negated: bool = False


@dataclass(frozen=True)
class InList(Expression):
    expression: Expression
    values: tuple[Expression, ...]
    negated: bool = False


@dataclass(frozen=True)
class AggregateCall(Expression):
    function: str
    argument: Expression
    distinct: bool = False


@dataclass(frozen=True)
class SelectItem(Node):
    expression: Expression
    alias: str | None = None


@dataclass(frozen=True)
class TableRef(Node):
    name: str
    alias: str | None = None


@dataclass(frozen=True)
class Join(Node):
    table: TableRef
    condition: Expression
    kind: str = "INNER"


@dataclass(frozen=True)
class OrderByItem(Node):
    expression: Expression
    direction: str = "ASC"
    nulls_first: bool | None = None


class Statement(Node):
    pass


@dataclass(frozen=True)
class ColumnDefinition(Node):
    name: str
    type: str
    size: int | None = None


@dataclass(frozen=True)
class CreateTableStatement(Statement):
    name: str
    columns: tuple[ColumnDefinition, ...]
    storage_method: str = "heap"


@dataclass(frozen=True)
class CreateIndexStatement(Statement):
    name: str
    table: str
    column: str
    method: str


@dataclass(frozen=True)
class SelectStatement(Statement):
    columns: tuple[SelectItem, ...]
    from_table: TableRef
    joins: tuple[Join, ...] = ()
    where: Expression | None = None
    group_by: tuple[Expression, ...] = ()
    having: Expression | None = None
    order_by: tuple[OrderByItem, ...] = ()
    distinct: bool = False
    limit: int | None = None
    offset: int | None = None


@dataclass(frozen=True)
class InsertStatement(Statement):
    table: str
    columns: tuple[str, ...] | None
    values: tuple[tuple[Literal, ...], ...]


@dataclass(frozen=True)
class DeleteStatement(Statement):
    table: TableRef
    where: Expression | None = None


@dataclass(frozen=True)
class TransactionStatement(Statement):
    action: str
