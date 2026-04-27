"""Database-side queries and writes used by the ingestion layer."""

from __future__ import annotations

import logging

from sqlalchemy import select

from db.database import get_session
from db.entities import Graph, GraphStatus, RepoClone

logger = logging.getLogger("meridian.db_utils")


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


def persist_clone(
    *,
    repo_id: str,
    owner: str,
    repo: str,
    repo_url: str,
    branch: str | None,
    path: str,
    user_id: str | None = None,
    last_commit_sha: str | None = None,
) -> None:
    """Upsert a `repo_clones` row. Re-cloning clears any prior `evicted_at`."""
    with get_session() as session:
        existing = session.get(RepoClone, repo_id)
        if existing is None:
            session.add(
                RepoClone(
                    repo_id=repo_id,
                    user_id=user_id,
                    owner=owner,
                    repo=repo,
                    repo_url=repo_url,
                    branch=branch,
                    path=path,
                    last_commit_sha=last_commit_sha,
                )
            )
            logger.info("db_utils: inserted repo_clone %s (%s/%s)", repo_id, owner, repo)
        else:
            existing.user_id = user_id
            existing.owner = owner
            existing.repo = repo
            existing.repo_url = repo_url
            existing.branch = branch
            existing.path = path
            existing.last_commit_sha = last_commit_sha
            existing.evicted_at = None
            logger.info("db_utils: refreshed repo_clone %s (%s/%s)", repo_id, owner, repo)
        session.commit()
