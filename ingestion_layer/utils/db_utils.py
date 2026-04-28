"""Database-side writes used by the ingestion layer.

Read-side queries that drive orchestration decisions (e.g. FULL vs PATCH)
live next to the orchestrator in `orchestrator/utils/db_utils.py` —
this module only owns writes for ingestion artifacts (clones).
"""

from __future__ import annotations

import logging

from db.database import get_session
from db.entities import RepoClone

logger = logging.getLogger("meridian.db_utils")


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
