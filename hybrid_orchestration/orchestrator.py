"""C4 — Agent SDK Orchestrator.

Single entry point that drives the full Meridian pipeline. Decides FULL vs
PATCH based on whether a READY graph already exists for `(repo_url, branch)`,
then chains the appropriate stages:

    FULL:   clone (subprocess git) → C5 parse → C6 resolve →
            C7 index_tree → C8 build_graph → persist `graphs` row
            (status='building' until C9 lands and re-clusters in place).

    PATCH:  git pull (subprocess) → diff → re-run C5/C6 on changed files →
            mutate stored tree → re-run C8 → re-cluster affected
            communities → persist. (Skeleton only — see _patch_sync.)

The ingestion layer below is intentionally dumb: it exposes `clone_repo`,
`persist_clone`, and (eventually) `pull_repo`/MCP enrichment. All decisions
about *what* to call live here.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from fastapi.concurrency import run_in_threadpool

from graph_engine.networkX_graph_builder import GraphBuildResult, build_graph
from graph_engine.utils.db_utils import persist_graph
from hybrid_orchestration.codebase_parser import parse_codebase
from hybrid_orchestration.codebase_parser.models import ParseResult
from hybrid_orchestration.surgical_agent import resolve_ambiguous
from hybrid_orchestration.tree_indexer import index_tree
from hybrid_orchestration.utils.db_utils import has_active_graph
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
    tree: ParseResult | None  # parse tree from C5/C6
    tree_id: str | None  # populated once the tree is indexed (C7)
    graph: GraphBuildResult | None  # populated once C8 has run
    graph_id: str | None  # populated once the graph is persisted (C10 stub)


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
    """Clone → C5 → C6 → C7 (index) → C8 (build) → persist `graphs` row."""
    branch_name = branch or "main"

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

    return OrchestrationResult(
        repo_url=repo_url,
        branch=branch_name,
        mode="FULL",
        clone=clone_result,
        tree=tree,
        tree_id=tree_id,
        graph=graph_result,
        graph_id=graph_id,
    )


async def _parse_and_resolve(repo: str) -> ParseResult:
    """C5 (tree-sitter, CPU-bound) → C6 (surgical Agent SDK, async)."""
    parse_result = await run_in_threadpool(parse_codebase, repo)
    return await resolve_ambiguous(parse_result)


async def _patch_sync(repo_url: str, pat: str, branch: str) -> None:
    """Template — incremental sync via `git pull` + GitHub MCP enrichment.

    TODO:
      1. `git pull` in the existing cache (subprocess, NOT MCP).
      2. `git diff <last_sha>..HEAD --name-status -M` → FileDiff.
      3. Load tree from DB, run C5/C6 on changed files only, mutate tree
         (drop nodes/edges from changed files, add re-parsed ones, fix
         cross-file edges), persist updated tree.
      4. Re-run C8 on the mutated tree, re-cluster only affected Leiden
         communities (C9), persist (C10).
      5. GitHub MCP `compare_commits` for PR/issue context on changed files.
    """
    logger.info(
        "orchestrator: PATCH not yet implemented (repo=%s branch=%s)",
        repo_url,
        branch,
    )
    return None
