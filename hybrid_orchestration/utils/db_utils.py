"""Database queries used by the orchestrator (C4).

Lives here (and not in `ingestion_layer/utils/`) because the FULL-vs-PATCH
decision is an orchestration-time concern — the ingestion layer just exposes
clone/pull primitives.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from db.database import get_session
from db.entities import Graph, GraphStatus

logger = logging.getLogger("meridian.orchestrator.db_utils")


def has_active_graph(repo_url: str, branch: str) -> bool:
    """True if a READY graph with non-empty graph_data exists for repo_url+branch."""
    stmt = select(Graph.graph_id).where(
        Graph.repo_url == repo_url,
        Graph.branch == branch,
        Graph.status == GraphStatus.READY.value,
        Graph.graph_data.is_not(None),
    )
    with get_session() as session:
        return session.execute(stmt).first() is not None
