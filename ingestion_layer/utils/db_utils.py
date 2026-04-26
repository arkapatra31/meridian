"""Database-side queries used by the ingestion layer."""

from __future__ import annotations

from sqlalchemy import select

from db.database import get_session
from db.entities import Graph, GraphStatus


def has_active_graph(repo_url: str, branch: str) -> bool:
    """True if an Active graph with non-empty graph_data exists for repo_url+branch."""
    stmt = select(Graph.graph_id).where(
        Graph.repo_url == repo_url,
        Graph.branch == branch,
        Graph.status == GraphStatus.ACTIVE.value,
        Graph.graph_data.is_not(None),
    )
    with get_session() as session:
        return session.execute(stmt).first() is not None
