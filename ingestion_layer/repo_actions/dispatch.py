"""Ingestion dispatcher — decides FULL vs PATCH and runs the build pipeline.

Single entry point for the ingestion layer. Looks up whether an active graph
already exists for `(repo_url, branch)` and routes accordingly:

- No active graph → `git clone` via subprocess (FULL build), then
  C5 (parse) → C6 (resolve) → tree_indexer (persist) inline.
- Active graph present → `git pull` + diff, run C5/C6 on changed files only,
  mutate the stored tree. (PATCH side still TODO.)

The returned `IngestionResult` carries the parse tree and its persisted
`tree_id` so the route layer can return both counts and a handle the client
can use to fetch the tree later.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from fastapi.concurrency import run_in_threadpool

from hybrid_orchestration.codebase_parser import parse_codebase
from hybrid_orchestration.codebase_parser.models import ParseResult
from hybrid_orchestration.surgical_agent import resolve_ambiguous
from hybrid_orchestration.tree_indexer import index_tree
from ingestion_layer.repo_cache.clone_repo import CloneResult, clone_repo
from ingestion_layer.utils.db_utils import has_active_graph, persist_clone

logger = logging.getLogger("meridian.repo_actions")

Mode = Literal["FULL", "PATCH"]


@dataclass(frozen=True)
class IngestionResult:
    repo_url: str
    branch: str
    mode: Mode
    clone: CloneResult | None  # populated when mode == "FULL"
    tree: ParseResult | None  # parse tree from C5/C6
    tree_id: str | None  # populated once the tree is indexed


async def sync_repo(
    repo_url: str,
    pat: str,
    branch: str | None = None,
) -> IngestionResult:
    """Decide FULL vs PATCH and run the matching ingestion + build path."""
    branch_name = branch or "main"

    if await asyncio.to_thread(has_active_graph, repo_url, branch_name):
        logger.info(
            "repo_actions: active graph exists for %s@%s — PATCH mode",
            repo_url,
            branch_name,
        )
        await _mcp_incremental_sync(repo_url, pat, branch_name)
        return IngestionResult(
            repo_url=repo_url,
            branch=branch_name,
            mode="PATCH",
            clone=None,
            tree=None,
            tree_id=None,
        )

    logger.info(
        "repo_actions: no active graph for %s@%s — FULL mode",
        repo_url,
        branch_name,
    )
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
    tree = await _run_full_pipeline(clone_result.repo)
    tree_id = await asyncio.to_thread(index_tree, tree)
    return IngestionResult(
        repo_url=repo_url,
        branch=branch_name,
        mode="FULL",
        clone=clone_result,
        tree=tree,
        tree_id=tree_id,
    )


async def _run_full_pipeline(repo: str) -> ParseResult:
    """C5 (parse) → C6 (resolve) for a freshly cloned repo.

    C5 is CPU-bound tree-sitter work, so it runs off the event loop. C6 is
    async-native and runs inline. The returned `ParseResult` is the parse
    tree that gets indexed and (eventually) fed to C8.
    """
    parse_result = await run_in_threadpool(parse_codebase, repo)
    return await resolve_ambiguous(parse_result)


async def _mcp_incremental_sync(repo_url: str, pat: str, branch: str) -> None:
    """Template — incremental sync via `git pull` + GitHub MCP enrichment.

    TODO:
      1. `git pull` in the existing cache (subprocess, NOT MCP).
      2. `git diff <last_sha>..HEAD --name-status -M` → FileDiff.
      3. Load tree from DB, run C5/C6 on changed files only, mutate tree
         (drop nodes/edges from changed files, add re-parsed ones, fix
         cross-file edges), persist updated tree.
      4. GitHub MCP `compare_commits` for PR/issue context on changed files.
    """
    logger.info(
        "repo_actions: PATCH not yet implemented (repo=%s branch=%s)",
        repo_url,
        branch,
    )
    return None
