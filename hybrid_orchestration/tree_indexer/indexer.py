"""Persist a C5+C6 parse tree into the `trees` table."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict

from db.database import get_session
from db.entities import Tree, TreeStatus
from hybrid_orchestration.codebase_parser.models import ParseResult

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
