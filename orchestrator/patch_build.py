"""PATCH (incremental sync) pipeline.

Drives a refresh-in-place when an active graph already exists for
`(repo_url, branch)`. Surgical shape — only touches what the diff says
changed:

    1. Look up active graph + its anchor SHA (`get_active_graph`).
    2. `git pull` the cached clone (re-cloning if the cache was evicted).
    3. No-op short-circuit when HEAD hasn't moved.
    4. On changes:
         - Re-parse ONLY `added ∪ modified ∪ renamed-to` files via
           `parse_files` — tree-sitter on the diff slice, not the repo.
         - Mutate the loaded tree (`mutate_tree`): drop nodes from
           `deleted ∪ modified ∪ renamed-from`, drop orphaned edges,
           drop stale ambiguous refs, splice in the delta nodes/edges.
         - Re-run C4b (`resolve_ambiguous`) on `delta.ambiguous` only.
           Carry-over unresolved refs from unchanged files are left as-is.
         - UPDATE the existing `trees` row in place (preserves `tree_id`)
           and the `graphs` row via `persist_graph`'s upsert.
         - Re-cluster the rebuilt graph.
    5. Audit row, mode='PATCH'. Snapshot to `graph_history`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi.concurrency import run_in_threadpool

from db.entities import SyncMode, SyncRunStatus
from graph_engine.leiden_clustering import cluster_graph
from graph_engine.networkX_graph_builder import build_graph
from graph_engine.utils.db_utils import record_graph_version
from hybrid_parsing.codebase_parser import parse_files
from hybrid_parsing.codebase_parser.models import ParseResult
from hybrid_parsing.surgical_agent import resolve_ambiguous
from hybrid_parsing.workload_reducer import reduce_workload
from hybrid_parsing.tree_indexer import (
    load_tree_as_parse_result,
    mutate_tree,
    update_tree,
)
from ingestion_layer.github_mcp.client import GithubMCPClient, GithubMCPError
from ingestion_layer.repo_cache.pull_repo import FileChange, PullResult, pull_repo
from ingestion_layer.utils.db_utils import persist_clone
from orchestrator.utils.db_utils import (
    ActiveGraph,
    get_active_graph,
    record_sync_run,
)

logger = logging.getLogger("meridian.orchestrator.patch_build")


async def patch_sync(
    repo_url: str, pat: str, branch: str, user_id: str | None = None
) -> str | None:
    """Run a PATCH sync for `(repo_url, branch)`. Returns the graph_id touched."""
    started_at = datetime.now(timezone.utc)

    if not user_id:
        raise RuntimeError("patch_sync called without user_id — orchestrator guard should have caught this")
    active = await asyncio.to_thread(get_active_graph, repo_url, branch, user_id)
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
            user_id=user_id,
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
    user_id: str | None = None,
) -> str:
    """Surgical: load tree → re-parse changed files → mutate → resolve delta
    → update tree → rebuild graph → re-cluster.
    """
    if active.tree_id is None:
        raise RuntimeError(
            f"patch_build: active graph {active.graph_id} has no linked tree"
        )

    stale_files, fresh_files = _split_diff(pull.changed_files)
    logger.info(
        "patch_build: surgical PATCH — stale=%d fresh=%d (graph_id=%s)",
        len(stale_files), len(fresh_files), active.graph_id,
    )

    # 1. Load existing tree from DB.
    existing = await asyncio.to_thread(load_tree_as_parse_result, active.tree_id)

    # 2. Re-parse only the fresh files (CPU-bound — off the event loop).
    delta = (
        await run_in_threadpool(parse_files, existing.repo, fresh_files)
        if fresh_files
        else _empty_parse_result(existing)
    )

    # 3. Splice: drop stale, add delta nodes/edges. Ambiguous routing is
    #    handled below — mutate_tree intentionally leaves that to the caller.
    merged = mutate_tree(existing, stale_files, delta)

    # 4. Re-resolve only the delta's new ambiguous refs. Carry-over unresolved
    #    refs (from unchanged files) stay as-is.
    carry_over = list(merged.ambiguous)
    new_ambig = list(delta.ambiguous)
    delta_ambig_count = len(new_ambig)
    merged.ambiguous = new_ambig
    if new_ambig:
        merged = await run_in_threadpool(reduce_workload, merged)
        if merged.ambiguous:
            merged = await resolve_ambiguous(merged)
    resolved_count = delta_ambig_count - len(merged.ambiguous)
    merged.ambiguous.extend(carry_over)

    logger.info(
        "patch_build: C4b on delta — input=%d resolved=%d remaining_in_delta=%d carry_over=%d",
        delta_ambig_count,
        resolved_count,
        delta_ambig_count - resolved_count,
        len(carry_over),
    )

    # 5. Persist mutated tree (preserves tree_id), rebuild graph, re-cluster.
    await asyncio.to_thread(
        update_tree, active.tree_id, merged, last_commit_sha=pull.current_sha
    )
    graph_result = await asyncio.to_thread(build_graph, active.tree_id)
    graph_id = active.graph_id
    await asyncio.to_thread(
        cluster_graph,
        graph_id,
        graph=graph_result.graph,
        node_count=graph_result.node_count,
        edge_count=graph_result.edge_count,
        last_commit_sha=pull.current_sha,
        repo_clone_id=pull.repo_id,
    )

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
        ambiguous_added=len(merged.ambiguous),
    )
    await asyncio.to_thread(record_graph_version, graph_id, run_id=run_id)
    return graph_id


def _split_diff(changes: list[FileChange]) -> tuple[set[str], list[str]]:
    """Partition the diff into (stale_paths, fresh_paths).

    stale = paths whose existing nodes/edges/ambiguous should be dropped:
            deleted ∪ modified (pre-mutation) ∪ renamed-from.
    fresh = paths to feed into `parse_files` for re-parse:
            added ∪ modified (re-parse) ∪ renamed-to.
    """
    stale: set[str] = set()
    fresh: list[str] = []
    for c in changes:
        if c.status == "A":
            fresh.append(c.path)
        elif c.status == "M":
            stale.add(c.path)
            fresh.append(c.path)
        elif c.status == "D":
            stale.add(c.path)
        elif c.status == "R":
            if c.old_path:
                stale.add(c.old_path)
            fresh.append(c.path)
    return stale, fresh


def _empty_parse_result(template: ParseResult) -> ParseResult:
    """An empty ParseResult sharing the template's repo/root — for D-only PATCHes."""
    return ParseResult(repo=template.repo, root=template.root)


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
