"""FULL build pipeline.

Clone → C4a parse → C4b resolve → C4c index_tree → C5a build_graph →
C5b cluster → link tree → audit row.

Invoked by `orchestrator.sync_repo` when no active graph exists for
`(repo_url, branch)`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from db.entities import SyncMode, SyncRunStatus
from graph_engine.leiden_clustering import cluster_graph
from graph_engine.networkX_graph_builder import build_graph
from graph_engine.utils.db_utils import (
    link_tree_to_graph,
    record_graph_version,
    reserve_graph,
)
from hybrid_parsing.codebase_parser import parse_codebase
from hybrid_parsing.codebase_parser.models import ParseResult
from hybrid_parsing.surgical_agent import resolve_ambiguous
from hybrid_parsing.tree_indexer import index_tree
from hybrid_parsing.workload_reducer import reduce_workload
from ingestion_layer.repo_cache.clone_repo import clone_repo
from ingestion_layer.utils.db_utils import persist_clone
from orchestrator.utils.db_utils import record_sync_run

from fastapi.concurrency import run_in_threadpool

from .types import OrchestrationResult

logger = logging.getLogger("meridian.orchestrator.full_build")


async def full_build(
    repo_url: str, pat: str, branch: str | None, user_id: str | None = None,
) -> OrchestrationResult:
    """Clone → C4a → C4b → C4c → C5a → C5b → link tree → audit row."""
    branch_name = branch or "main"
    started_at = datetime.now(timezone.utc)

    clone_result = await clone_repo(repo_url, pat, branch=branch)
    await asyncio.to_thread(
        persist_clone,
        repo_id=clone_result.repo_id,
        owner=clone_result.owner,
        repo=clone_result.repo,
        repo_url=repo_url,
        branch=clone_result.branch,
        path=str(clone_result.path),
        last_commit_sha=clone_result.last_commit_sha,
    )

    # Reserve (or re-confirm) the graph_id for this build. The route already
    # called reserve_graph before dispatching; this UPSERT is idempotent and
    # returns the same graph_id so downstream steps have it without threading
    # it through the call stack.
    graph_id = await asyncio.to_thread(
        reserve_graph, repo_url, branch_name, user_id or ""
    )

    tree = await _parse_and_resolve(clone_result.repo)
    tree_id = await asyncio.to_thread(
        index_tree, tree, last_commit_sha=clone_result.last_commit_sha
    )
    graph_result = await asyncio.to_thread(build_graph, tree_id)
    cluster_result = await asyncio.to_thread(
        cluster_graph,
        graph_id,
        graph=graph_result.graph,
        node_count=graph_result.node_count,
        edge_count=graph_result.edge_count,
        last_commit_sha=graph_result.last_commit_sha,
        repo_clone_id=clone_result.repo_id,
    )

    # C5b just flipped the graphs row to READY. Link this build's tree onto
    # the (now final) graph_id, evicting any stale tree from a prior build,
    # then drop the audit row.
    await asyncio.to_thread(link_tree_to_graph, tree_id, graph_id)
    run_id = await asyncio.to_thread(
        record_sync_run,
        graph_id=graph_id,
        mode=SyncMode.FULL,
        status=SyncRunStatus.SUCCESS,
        started_at=started_at,
        current_sha=graph_result.last_commit_sha,
        nodes_added=graph_result.node_count,
        edges_added=graph_result.edge_count,
        ambiguous_added=len(tree.ambiguous),
    )
    await asyncio.to_thread(record_graph_version, graph_id, run_id=run_id)

    return OrchestrationResult(
        repo_url=repo_url,
        branch=branch_name,
        mode="FULL",
        clone=clone_result,
        tree=tree,
        tree_id=tree_id,
        graph=graph_result,
        graph_id=graph_id,
        cluster=cluster_result,
    )


async def _parse_and_resolve(repo: str) -> ParseResult:
    """C4a → Pass 1.5 workload reducer → C4b (only if refs remain)."""
    parse_result = await run_in_threadpool(parse_codebase, repo)
    parse_result = await run_in_threadpool(reduce_workload, parse_result)
    if parse_result.ambiguous:
        parse_result = await resolve_ambiguous(parse_result)
    return parse_result
