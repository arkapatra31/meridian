"""Data types for C7 — the diff engine.

In FULL mode (first build of a repo), there is no prior state — the diff is
"everything is new". The engine wraps the C6 `ParseResult` in a `DiffResult`
whose summary reports every node/edge/ambiguous-ref as an addition. PATCH
mode (driven by file-level diffs returned from the ingestion layer's MCP
sync) will reuse the same `DiffResult` shape with non-zero removals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..codebase_parser.models import ParseResult

DiffMode = Literal["FULL", "PATCH"]


@dataclass
class DiffSummary:
    mode: DiffMode = "FULL"
    nodes_added: int = 0
    nodes_removed: int = 0
    edges_added: int = 0
    edges_removed: int = 0
    ambiguous_added: int = 0
    ambiguous_removed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class DiffResult:
    """Output of the diff engine.

    `graph` is the (possibly mutated) `ParseResult`. `summary` is a small
    audit trail safe to log or surface to the API. `previous_sha` /
    `current_sha` are echoed so the caller can persist `current_sha` back
    to `graphs.last_commit_sha` once C8 finalizes the build.
    """

    repo: str
    previous_sha: str | None
    current_sha: str | None
    graph: ParseResult
    summary: DiffSummary
