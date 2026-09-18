"""Errores de SQL con ubicación en el texto original."""


class SQLError(ValueError):
    def __init__(self, message: str, source: str, offset: int, line: int, column: int):
        self.message = message
        self.offset = offset
        self.line = line
        self.column = column
        lines = source.split("\n")
        text = lines[line - 1] if line <= len(lines) else ""
        super().__init__(f"{message} (línea {line}, columna {column})\n{text}\n{' ' * (column - 1)}^")


class SQLLexError(SQLError):
    """Carácter, literal o comentario inválido."""


class SQLParseError(SQLError):
    """La secuencia de tokens no pertenece a la gramática soportada."""


class SQLSemanticError(ValueError):
    """Tabla, columna, tipo o operación incompatible con el catálogo/motor."""


class SQLExecutionError(RuntimeError):
    """Una expresión no puede evaluarse sobre los datos actuales."""
