"""C7 entry — `run_diff_engine`.

Sits at the tail of the build pipeline:

    sync → dispatch → C5 (parse) → C6 (resolve) → C7 (this)

In FULL mode (first build of a repo), there is no prior graph to compare
against — the diff is "everything is new". The engine wraps the C6
`ParseResult` in a `DiffResult` whose summary mirrors the full
node/edge/ambiguous counts. PATCH mode (driven by file-level diffs from
the ingestion layer's MCP sync) will share this entry function and the
`DiffResult` shape, just with non-zero removals.
"""

from __future__ import annotations

import logging

from ..codebase_parser.models import ParseResult
from .models import DiffResult, DiffSummary

logger = logging.getLogger("meridian.diff_engine")


def run_diff_engine(
    parse_result: ParseResult,
    *,
    previous_sha: str | None = None,
    current_sha: str | None = None,
) -> DiffResult:
    """Wrap the C6 graph in a `DiffResult` for downstream consumers.

    In FULL mode this is effectively a typed passthrough — the caller
    receives the same graph plus a summary that reports the entire content
    as additions. The signature is stable so PATCH mode can slot in here
    later without touching call sites.
    """
    summary = DiffSummary(
        mode="FULL",
        nodes_added=len(parse_result.nodes),
        edges_added=len(parse_result.edges),
        ambiguous_added=len(parse_result.ambiguous),
        errors=list(parse_result.errors),
    )

    logger.info(
        "diff_engine: FULL mode repo=%s nodes=%d edges=%d ambiguous=%d",
        parse_result.repo,
        summary.nodes_added,
        summary.edges_added,
        summary.ambiguous_added,
    )

    return DiffResult(
        repo=parse_result.repo,
        previous_sha=previous_sha,
        current_sha=current_sha,
        graph=parse_result,
        summary=summary,
    )
