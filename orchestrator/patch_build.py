"""PATCH (incremental sync) pipeline.

Drives a refresh-in-place when an active graph already exists for
`(repo_url, branch)`. Shape:

    1. Look up active graph + its anchor SHA (`get_active_graph`).
    2. `git pull` the cached clone (re-cloning if the cache was evicted).
    3. No-op short-circuit when HEAD hasn't moved — bumps `last_accessed_at`
       and writes a SUCCESS audit row with zero deltas.
    4. On changes: opportunistic MCP enrichment (commit list between SHAs,
       logged only — non-blocking), then full re-parse + re-resolve, mutate
       the existing `trees` row in place, UPDATE the `graphs` row via the
       same `persist_graph` upsert FULL uses, and re-cluster.
    5. Audit row, mode='PATCH'.

v1 cut: re-parses the entire repo on changes (cheap — ~10k files/s) and
re-resolves the full ambiguous set. The architectural payoff today is
(a) avoiding a re-clone on every sync and (b) zero work when nothing
changed (the most common case for re-syncs). v2 will narrow the
re-parse + re-resolve to changed files only and mutate the tree in
place.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from db.entities import SyncMode, SyncRunStatus
from graph_engine.leiden_clustering import cluster_graph
from graph_engine.networkX_graph_builder import build_graph
from graph_engine.utils.db_utils import persist_graph, record_graph_version
from hybrid_parsing.tree_indexer import update_tree
from ingestion_layer.github_mcp.client import GithubMCPClient, GithubMCPError
from ingestion_layer.repo_cache.pull_repo import PullResult, pull_repo
from ingestion_layer.utils.db_utils import persist_clone
from orchestrator.utils.db_utils import (
    ActiveGraph,
    get_active_graph,
    record_sync_run,
)

from .full_build import _parse_and_resolve

logger = logging.getLogger("meridian.orchestrator.patch_build")


async def patch_sync(repo_url: str, pat: str, branch: str) -> str | None:
    """Run a PATCH sync for `(repo_url, branch)`. Returns the graph_id touched."""
    started_at = datetime.now(timezone.utc)

    active = await asyncio.to_thread(get_active_graph, repo_url, branch)
    if active is None:
        # The dispatcher already saw `has_active_graph == True`; if we get
        # here the row was deleted between the two calls. Surface as a soft
        # error rather than silently full-rebuilding.
        logger.warning(
            "patch_build: active graph disappeared mid-dispatch (%s@%s)",
            repo_url, branch,
        )
        return None

    if not active.previous_sha:
        # Need an anchor for the diff. Old rows from before the SHA leak
        # was fixed may be missing one — caller should manual-rebuild instead.
        logger.error(
            "patch_build: active graph %s has no previous_sha — manual rebuild required",
            active.graph_id,
        )
        await asyncio.to_thread(
            record_sync_run,
            graph_id=active.graph_id,
            mode=SyncMode.PATCH,
            status=SyncRunStatus.ERROR,
            started_at=started_at,
            error_message="missing previous_sha; rebuild required",
        )
        return active.graph_id

    pull = await pull_repo(
        repo_url, pat, branch=branch, previous_sha=active.previous_sha
    )

    # Refresh clone tombstone with the new SHA + access timestamp.
    await asyncio.to_thread(
        persist_clone,
        repo_id=pull.repo_id,
        owner=pull.owner,
        repo=pull.repo,
        repo_url=repo_url,
        branch=pull.branch,
        path=str(pull.path),
        last_commit_sha=pull.current_sha,
    )

    if not pull.has_changes:
        logger.info(
            "patch_build: no commits since %s — no-op sync (graph_id=%s)",
            active.previous_sha[:8], active.graph_id,
        )
        await asyncio.to_thread(
            record_sync_run,
            graph_id=active.graph_id,
            mode=SyncMode.PATCH,
            status=SyncRunStatus.SUCCESS,
            started_at=started_at,
            previous_sha=active.previous_sha,
            current_sha=pull.current_sha,
        )
        return active.graph_id

    # MCP enrichment runs in parallel with the rebuild — best-effort log only.
    enrichment_task = asyncio.create_task(
        _log_mcp_enrichment(repo_url, pat, branch, pull)
    )

    try:
        graph_id = await _refresh_graph(
            active=active,
            pull=pull,
            repo_url=repo_url,
            branch=branch,
            started_at=started_at,
        )
    except Exception as exc:  # noqa: BLE001 — any failure must land in the audit row
        logger.exception("patch_build: rebuild failed for %s", active.graph_id)
        await asyncio.to_thread(
            record_sync_run,
            graph_id=active.graph_id,
            mode=SyncMode.PATCH,
            status=SyncRunStatus.ERROR,
            started_at=started_at,
            previous_sha=active.previous_sha,
            current_sha=pull.current_sha,
            error_message=str(exc),
        )
        raise
    finally:
        # Don't let a slow / failing MCP call hold the request open.
        if not enrichment_task.done():
            enrichment_task.cancel()

    return graph_id


async def _refresh_graph(
    *,
    active: ActiveGraph,
    pull: PullResult,
    repo_url: str,
    branch: str,
    started_at: datetime,
) -> str:
    """Re-parse, re-resolve, update tree row, rebuild graph, re-cluster."""
    if active.tree_id is None:
        raise RuntimeError(
            f"patch_build: active graph {active.graph_id} has no linked tree — "
            "cannot PATCH; manual rebuild required"
        )

    tree = await _parse_and_resolve(pull.repo)
    await asyncio.to_thread(
        update_tree, active.tree_id, tree, last_commit_sha=pull.current_sha
    )

    graph_result = await asyncio.to_thread(build_graph, active.tree_id)
    graph_id = await asyncio.to_thread(
        persist_graph,
        graph_result.graph,
        repo_url=repo_url,
        branch=branch,
        repo_clone_id=pull.repo_id,
        last_commit_sha=pull.current_sha,
    )

    await asyncio.to_thread(cluster_graph, graph_id)

    run_id = await asyncio.to_thread(
        record_sync_run,
        graph_id=graph_id,
        mode=SyncMode.PATCH,
        status=SyncRunStatus.SUCCESS,
        started_at=started_at,
        previous_sha=active.previous_sha,
        current_sha=pull.current_sha,
        nodes_added=graph_result.node_count,
        edges_added=graph_result.edge_count,
        ambiguous_added=len(tree.ambiguous),
    )
    await asyncio.to_thread(record_graph_version, graph_id, run_id=run_id)
    return graph_id


async def _log_mcp_enrichment(
    repo_url: str, pat: str, branch: str, pull: PullResult
) -> None:
    """Best-effort: log commits between SHAs via the GitHub MCP server.

    Non-blocking, non-fatal. Adds PR/commit context to the build log
    without holding up the rebuild on a flaky MCP connection.
    """
    try:
        async with GithubMCPClient(repo_url, pat, branch=branch) as gh:
            commits = await gh.commits_between(pull.previous_sha, pull.current_sha)
            logger.info(
                "patch_build: %d commits between %s..%s (%d changed files)",
                len(commits),
                pull.previous_sha[:8],
                pull.current_sha[:8],
                len(pull.changed_files),
            )
            for c in commits[:10]:
                msg = (c.get("commit") or {}).get("message", "").split("\n", 1)[0]
                sha = (c.get("sha") or "")[:8]
                logger.debug("  %s %s", sha, msg)
    except asyncio.CancelledError:
        raise
    except (GithubMCPError, Exception) as exc:  # noqa: BLE001
        logger.warning("patch_build: MCP enrichment skipped — %s", exc)
