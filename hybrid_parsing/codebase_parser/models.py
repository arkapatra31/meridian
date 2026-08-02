"""Data types produced by Pass 1 (tree-sitter) parsing.

Mirrors the node/edge schema in CLAUDE.md so results drop straight into the
graph builder (C5a) without translation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

NodeType = Literal["module", "class", "function", "method"]
EdgeType = Literal[
    "IMPORTS", "CALLS", "CONTAINS", "INHERITS", "DECORATES", "RELATES_TO", "DEPENDS_ON"
]
Confidence = Literal["EXTRACTED", "INFERRED"]
AmbiguousKind = Literal["import", "call", "decorator", "inherits"]


@dataclass
class Node:
    id: str
    type: NodeType
    name: str
    file: str
    line_start: int
    line_end: int
    language: str
    params: list[str] = field(default_factory=list)
    docstring: str | None = None
    return_type: str | None = None


@dataclass
class Edge:
    source: str
    target: str
    type: EdgeType
    confidence: Confidence = "EXTRACTED"
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AmbiguousRef:
    """A reference tree-sitter saw but couldn't fully resolve.

    Pass 2 (C4b, the surgical Agent SDK) consumes these and produces INFERRED edges.
    """

    source: str
    raw: str
    kind: AmbiguousKind
    file: str
    line: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    repo: str
    root: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    ambiguous: list[AmbiguousRef] = field(default_factory=list)
    files_parsed: int = 0
    files_skipped: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
