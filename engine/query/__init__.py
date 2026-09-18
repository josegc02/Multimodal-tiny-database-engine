"""Procesamiento y optimización de consultas SQL."""

from engine.query.errors import SQLError, SQLLexError, SQLParseError
from engine.query.lexer import Lexer, Token, tokenize
from engine.query.parser import Parser, parse, parse_script
from engine.query.catalog import Catalog
from engine.query.logical_plan import LogicalPlan, LogicalPlanner
from engine.query.sql_executor import SQLExecutor
from engine.query.errors import SQLSemanticError, SQLExecutionError
from engine.query.planner import IndexInfo, TableStats

__all__ = [
    "Lexer", "Token", "tokenize", "Parser", "parse", "parse_script",
    "SQLError", "SQLLexError", "SQLParseError",
    "Catalog", "LogicalPlan", "LogicalPlanner", "SQLExecutor",
    "SQLSemanticError", "SQLExecutionError",
    "IndexInfo", "TableStats",
]
