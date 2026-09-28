"""Small, replaceable source parsers. Only Python has syntax analysis."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Protocol

from middle_man.gateway.models import ImportRecord, Symbol


@dataclass(frozen=True, slots=True)
class ParseResult:
    symbols: tuple[Symbol, ...] = ()
    imports: tuple[ImportRecord, ...] = ()
    error: str | None = None


class LanguageParser(Protocol):
    def parse(self, path: str, source: str) -> ParseResult: ...


class PlainTextParser:
    def parse(self, path: str, source: str) -> ParseResult:
        return ParseResult()


class PythonParser:
    def parse(self, path: str, source: str) -> ParseResult:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            return ParseResult(error=f"{exc.msg} (line {exc.lineno})")
        symbols: list[Symbol] = []
        imports: list[ImportRecord] = []

        def visit(nodes: list[ast.stmt], parent: str | None = None, in_class: bool = False) -> None:
            for node in nodes:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = f"{parent}.{node.name}" if parent else node.name
                    kind = "class" if isinstance(node, ast.ClassDef) else "method" if in_class else "function"
                    symbols.append(Symbol(path, node.name, qualified, kind, node.lineno, getattr(node, "end_lineno", None), parent,
                                          tuple(ast.unparse(item) for item in node.decorator_list), isinstance(node, ast.AsyncFunctionDef)))
                    visit(node.body, qualified, isinstance(node, ast.ClassDef))
                elif isinstance(node, ast.Import):
                    imports.extend(ImportRecord(alias.name, line=node.lineno) for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.extend(ImportRecord(node.module or "", alias.name, node.level, node.lineno) for alias in node.names)
                elif parent is None and isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id.isupper():
                            symbols.append(Symbol(path, target.id, target.id, "constant", node.lineno, getattr(node, "end_lineno", None)))
                elif isinstance(node, (ast.If, ast.Try, ast.With)):
                    visit(node.body, parent, in_class)
                    if isinstance(node, (ast.If, ast.Try)):
                        visit(node.orelse if isinstance(node, ast.If) else node.finalbody, parent, in_class)
                        if isinstance(node, ast.Try):
                            for handler in node.handlers:
                                visit(handler.body, parent, in_class)
        visit(tree.body)
        return ParseResult(tuple(symbols), tuple(imports))


class ParserRegistry:
    def __init__(self, python_parser: LanguageParser | None = None) -> None:
        self._python = python_parser or PythonParser()
        self._plain = PlainTextParser()

    def for_language(self, language: str) -> LanguageParser:
        return self._python if language == "Python" else self._plain
