"""Persist or refresh a C4a+C4b parse tree in the `trees` table."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from db.database import get_session
from db.entities import Tree, TreeStatus
from hybrid_parsing.codebase_parser.models import ParseResult

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
