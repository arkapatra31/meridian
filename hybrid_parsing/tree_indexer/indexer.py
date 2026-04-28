"""Persist or refresh a C4a+C4b parse tree in the `trees` table."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from db.database import get_session
from db.entities import Tree, TreeStatus
from hybrid_parsing.codebase_parser.models import (
    AmbiguousRef,
    Edge,
    Node,
    ParseResult,
)

logger = logging.getLogger("meridian.tree_indexer")


def index_tree(
    parse_result: ParseResult,
    *,
    graph_id: str | None = None,
    last_commit_sha: str | None = None,
) -> str:
    """Insert a `trees` row from a parse_result and return the new tree_id."""
    tree_id = str(uuid.uuid4())

    with get_session() as session:
        session.add(
            Tree(
                tree_id=tree_id,
                graph_id=graph_id,
                tree_data=asdict(parse_result),
                last_commit_sha=last_commit_sha,
                status=TreeStatus.READY.value,
                node_count=len(parse_result.nodes),
                edge_count=len(parse_result.edges),
                ambiguous_count=len(parse_result.ambiguous),
            )
        )
        session.commit()

    logger.info(
        "tree_indexer: indexed %s (nodes=%d edges=%d ambiguous=%d)",
        tree_id,
        len(parse_result.nodes),
        len(parse_result.edges),
        len(parse_result.ambiguous),
    )
    return tree_id


def load_tree_as_parse_result(tree_id: str) -> ParseResult:
    """Reconstitute a `trees.tree_data` row into a ParseResult.

    Used by the PATCH path so we can mutate the existing tree in memory and
    write it back via `update_tree`. The dict→dataclass inversion mirrors
    the `asdict(parse_result)` call in `index_tree` / `update_tree`.
    """
    with get_session() as session:
        row = session.get(Tree, tree_id)
        if row is None:
            raise ValueError(f"tree_indexer.load: tree_id {tree_id!r} not found")
        if row.tree_data is None:
            raise ValueError(f"tree_indexer.load: tree {tree_id!r} has no tree_data")
        data = row.tree_data

    return ParseResult(
        repo=data["repo"],
        root=data["root"],
        nodes=[Node(**n) for n in data.get("nodes", [])],
        edges=[Edge(**e) for e in data.get("edges", [])],
        ambiguous=[AmbiguousRef(**a) for a in data.get("ambiguous", [])],
        files_parsed=data.get("files_parsed", 0),
        files_skipped=data.get("files_skipped", 0),
        languages=dict(data.get("languages", {})),
        errors=list(data.get("errors", [])),
    )


def mutate_tree(
    existing: ParseResult,
    stale_files: set[str],
    delta: ParseResult,
) -> ParseResult:
    """In-place surgical merge: drop stale, splice delta nodes/edges.

    Pure structural mutation — does NOT call C4b. The caller decides
    resolution policy (typically: re-resolve only `delta.ambiguous` and
    leave previously-unresolved refs in unchanged files alone). This is
    why `delta.ambiguous` is NOT appended here — the caller routes it
    through the resolver before merging.

    Args:
        existing: tree loaded from DB (mutated in place and returned)
        stale_files: paths to drop nodes/edges/ambiguous for — typically
            `deleted ∪ modified ∪ renamed-from`
        delta: fresh parse output for `added ∪ modified ∪ renamed-to`
    """
    # IDs about to be dropped (nodes from stale files).
    removed_ids = {n.id for n in existing.nodes if n.file in stale_files}
    # IDs the delta will re-introduce (same logical symbol, re-parsed).
    returning_ids = {n.id for n in delta.nodes}
    # Truly gone — neither in the surviving tree nor in the delta. e.g. a
    # function deleted in a modified file, or any node from a deleted file.
    truly_removed = removed_ids - returning_ids

    # Drop nodes from stale files.
    existing.nodes = [n for n in existing.nodes if n.file not in stale_files]

    # Edge survival rules:
    #   1. Source ∈ removed_ids → drop. The delta re-emits whatever the new
    #      version of that file emits; keeping the old edges would leave
    #      stale edges (e.g. a CALL that no longer exists in the new code).
    #   2. Target ∈ truly_removed → drop. Pointer into a gone symbol.
    #   3. Otherwise → keep. Crucially this preserves INFERRED cross-file
    #      edges from UNCHANGED files into MODIFIED-but-returning targets:
    #      same node ID survives the re-parse, so the resolution stays
    #      valid. Without this rule we silently lose every C4b-resolved
    #      cross-file edge into a modified file on every PATCH (because we
    #      don't re-parse the unchanged source files, so the original
    #      AmbiguousRef can't be re-resolved). It also preserves edges
    #      pointing at synthetic external IDs (cross-repo imports like
    #      `os::module`) since those are never in `removed_ids`.
    existing.edges = [
        e
        for e in existing.edges
        if e.source not in removed_ids and e.target not in truly_removed
    ]

    # Drop ambiguous refs whose source file is gone — re-resolution would
    # be pointless since the node that referenced them no longer exists.
    existing.ambiguous = [a for a in existing.ambiguous if a.file not in stale_files]

    # Splice in the delta. Note: ambiguous is NOT merged here — see
    # docstring; the caller routes `delta.ambiguous` through C4b first.
    existing.nodes.extend(delta.nodes)
    existing.edges.extend(delta.edges)

    # Counter housekeeping. Absolute totals are no longer meaningful after
    # a partial re-parse; we keep the larger of (existing, delta) and let
    # the orchestrator's audit row carry the diff stats. Languages are
    # summed; new errors are appended.
    existing.files_parsed = max(existing.files_parsed, delta.files_parsed)
    existing.files_skipped = max(existing.files_skipped, delta.files_skipped)
    for lang, n in delta.languages.items():
        existing.languages[lang] = existing.languages.get(lang, 0) + n
    if delta.errors:
        existing.errors.extend(delta.errors)

    return existing


def update_tree(
    tree_id: str,
    parse_result: ParseResult,
    *,
    last_commit_sha: str | None = None,
) -> None:
    """Overwrite an existing `trees` row with a refreshed parse_result.

    PATCH path: the `tree_id` is preserved (so `graphs.tree_id` and any
    cross-references stay valid) but `tree_data` and the denormalized
    counters are rewritten in place. Bumps `updated_at`.
    """
    with get_session() as session:
        row = session.get(Tree, tree_id)
        if row is None:
            raise ValueError(f"tree_indexer.update_tree: tree_id {tree_id!r} not found")
        row.tree_data = asdict(parse_result)
        row.status = TreeStatus.READY.value
        row.node_count = len(parse_result.nodes)
        row.edge_count = len(parse_result.edges)
        row.ambiguous_count = len(parse_result.ambiguous)
        if last_commit_sha is not None:
            row.last_commit_sha = last_commit_sha
        row.updated_at = datetime.now(timezone.utc)
        session.commit()

    logger.info(
        "tree_indexer: updated %s (nodes=%d edges=%d ambiguous=%d)",
        tree_id,
        len(parse_result.nodes),
        len(parse_result.edges),
        len(parse_result.ambiguous),
    )
