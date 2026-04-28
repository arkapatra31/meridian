"""Database queries used by the orchestrator (C2).

Lives here (and not in `ingestion_layer/utils/`) because the FULL-vs-PATCH
decision and the sync-run audit are orchestration-time concerns — the
ingestion layer just exposes clone/pull primitives.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from db.database import get_session
from db.entities import Graph, GraphStatus, SyncMode, SyncRun, SyncRunStatus, Tree

logger = logging.getLogger("meridian.orchestrator.db_utils")


@dataclass(frozen=True)
class ActiveGraph:
    """Read-only handle returned by `get_active_graph` for the PATCH path."""

    graph_id: str
    tree_id: str | None
    repo_clone_id: str | None
    previous_sha: str | None


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


def get_active_graph(repo_url: str, branch: str) -> ActiveGraph | None:
    """Fetch the IDs + last_commit_sha needed to drive a PATCH.

    Returns the active READY graph for `(repo_url, branch)` along with its
    linked tree id and the SHA we last anchored on. Used by `patch_sync` to
    avoid re-loading the row downstream and to compute the pull diff.
    """
    stmt = (
        select(
            Graph.graph_id,
            Graph.repo_clone_id,
            Graph.last_commit_sha,
            Tree.tree_id,
        )
        .outerjoin(Tree, Tree.graph_id == Graph.graph_id)
        .where(
            Graph.repo_url == repo_url,
            Graph.branch == branch,
            Graph.status == GraphStatus.READY.value,
            Graph.graph_data.is_not(None),
        )
        .limit(1)
    )
    with get_session() as session:
        row = session.execute(stmt).first()
    if row is None:
        return None
    graph_id, repo_clone_id, last_sha, tree_id = row
    return ActiveGraph(
        graph_id=graph_id,
        tree_id=tree_id,
        repo_clone_id=repo_clone_id,
        previous_sha=last_sha,
    )


def record_sync_run(
    *,
    graph_id: str,
    mode: SyncMode,
    status: SyncRunStatus,
    started_at: datetime,
    previous_sha: str | None = None,
    current_sha: str | None = None,
    nodes_added: int = 0,
    nodes_removed: int = 0,
    edges_added: int = 0,
    edges_removed: int = 0,
    ambiguous_added: int = 0,
    ambiguous_removed: int = 0,
    error_message: str | None = None,
) -> str:
    """Insert one `sync_runs` audit row at the end of a build / sync.

    Single insert (not upsert): every run gets its own audit trail entry so
    we can reconstruct build history. The `started_at` is captured by the
    orchestrator before clone/parse so the duration reflects the full
    pipeline, not just the DB write.
    """
    run_id = str(uuid.uuid4())
    with get_session() as session:
        session.add(
            SyncRun(
                run_id=run_id,
                graph_id=graph_id,
                mode=mode.value,
                status=status.value,
                previous_sha=previous_sha,
                current_sha=current_sha,
                nodes_added=nodes_added,
                nodes_removed=nodes_removed,
                edges_added=edges_added,
                edges_removed=edges_removed,
                ambiguous_added=ambiguous_added,
                ambiguous_removed=ambiguous_removed,
                error_message=error_message,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    logger.info(
        "db_utils: recorded sync_run %s (graph_id=%s mode=%s status=%s)",
        run_id,
        graph_id,
        mode.value,
        status.value,
    )
    return run_id
