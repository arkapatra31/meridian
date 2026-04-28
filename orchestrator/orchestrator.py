"""C2 — Agent SDK Orchestrator.

Single entry point that drives the full Meridian pipeline. Decides FULL vs
PATCH based on whether a READY graph already exists for `(repo_url, branch)`,
then chains the appropriate stages:

    FULL:   clone (subprocess git) → C4a parse → C4b resolve →
            C4c index_tree → C5a build_graph → persist `graphs` row
            (status='BUILDING' until C5b lands and re-clusters in place).

    PATCH:  git pull (subprocess) → diff → re-run C4a/C4b on changed files →
            mutate stored tree → re-run C5a → re-cluster affected
            communities → persist. (Skeleton only — see _patch_sync.)

The ingestion layer below is intentionally dumb: it exposes `clone_repo`,
`persist_clone`, and (eventually) `pull_repo`/MCP enrichment. All decisions
about *what* to call live here.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from fastapi.concurrency import run_in_threadpool

from db.entities import SyncMode, SyncRunStatus
from graph_engine.leiden_clustering import ClusterResult, cluster_graph
from graph_engine.networkX_graph_builder import GraphBuildResult, build_graph
from graph_engine.utils.db_utils import link_tree_to_graph, persist_graph
from hybrid_parsing.codebase_parser import parse_codebase
from hybrid_parsing.codebase_parser.models import ParseResult
from hybrid_parsing.surgical_agent import resolve_ambiguous
from hybrid_parsing.tree_indexer import index_tree
from orchestrator.utils.db_utils import has_active_graph, record_sync_run
from ingestion_layer.repo_cache.clone_repo import CloneResult, clone_repo
from ingestion_layer.utils.db_utils import persist_clone

logger = logging.getLogger("meridian.orchestrator")

Mode = Literal["FULL", "PATCH"]


@dataclass(frozen=True)
class OrchestrationResult:
    repo_url: str
    branch: str
    mode: Mode
    clone: CloneResult | None  # populated when mode == "FULL"
    tree: ParseResult | None  # parse tree from C4a/C4b
    tree_id: str | None  # populated once the tree is indexed (C4c)
    graph: GraphBuildResult | None  # populated once C5a has run
    graph_id: str | None  # populated once the graph is persisted (C8 stub)
    cluster: ClusterResult | None  # populated once C5b has clustered the graph


async def sync_repo(
    repo_url: str,
    pat: str,
    branch: str | None = None,
) -> OrchestrationResult:
    """Decide FULL vs PATCH and run the matching pipeline."""
    branch_name = branch or "main"

    if await asyncio.to_thread(has_active_graph, repo_url, branch_name):
        logger.info(
            "orchestrator: active graph exists for %s@%s — PATCH mode",
            repo_url,
            branch_name,
        )
        await _patch_sync(repo_url, pat, branch_name)
        return OrchestrationResult(
            repo_url=repo_url,
            branch=branch_name,
            mode="PATCH",
            clone=None,
            tree=None,
            tree_id=None,
            graph=None,
            graph_id=None,
            cluster=None,
        )

    logger.info(
        "orchestrator: no active graph for %s@%s — FULL mode",
        repo_url,
        branch_name,
    )
    return await _full_build(repo_url, pat, branch)


async def _full_build(
    repo_url: str, pat: str, branch: str | None
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
    )

    tree = await _parse_and_resolve(clone_result.repo)
    tree_id = await asyncio.to_thread(index_tree, tree)
    graph_result = await asyncio.to_thread(build_graph, tree_id)
    graph_id = await asyncio.to_thread(
        persist_graph,
        graph_result.graph,
        repo_url=repo_url,
        branch=branch_name,
        repo_clone_id=clone_result.repo_id,
        last_commit_sha=graph_result.last_commit_sha,
    )
    cluster_result = await asyncio.to_thread(cluster_graph, graph_id)

    # C5b just flipped the graphs row to READY. Link this build's tree onto
    # the (now final) graph_id, evicting any stale tree from a prior build,
    # then drop the audit row.
    await asyncio.to_thread(link_tree_to_graph, tree_id, graph_id)
    await asyncio.to_thread(
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
    """C4a (tree-sitter, CPU-bound) → C4b (surgical Agent SDK, async)."""
    parse_result = await run_in_threadpool(parse_codebase, repo)
    return await resolve_ambiguous(parse_result)


async def _patch_sync(repo_url: str, pat: str, branch: str) -> None:
    """Template — incremental sync via `git pull` + GitHub MCP enrichment.

    TODO:
      1. `git pull` in the existing cache (subprocess, NOT MCP).
      2. `git diff <last_sha>..HEAD --name-status -M` → FileDiff.
      3. Load tree from DB, run C4a/C4b on changed files only, mutate tree
         (drop nodes/edges from changed files, add re-parsed ones, fix
         cross-file edges), persist updated tree.
      4. Re-run C5a on the mutated tree, re-cluster only affected Leiden
         communities (C5b), persist (C8).
      5. GitHub MCP `compare_commits` for PR/issue context on changed files.
    """
    logger.info(
        "orchestrator: PATCH not yet implemented (repo=%s branch=%s)",
        repo_url,
        branch,
    )
    return None
