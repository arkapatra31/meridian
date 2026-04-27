"""Ingestion dispatcher — decides FULL vs PATCH and runs the build pipeline.

Single entry point for the ingestion layer. Looks up whether an active graph
already exists for `(repo_url, branch)` and routes accordingly:

- No active graph → `git clone` via subprocess (FULL build), then
  C5 (parse) → C6 (resolve) → C7 (diff engine) inline.
- Active graph present → GitHub MCP incremental sync (PATCH), feeding the
  resulting file diff into C7. (PATCH side still TODO.)

The returned `IngestionResult` carries both the ingestion mode and the
final `DiffResult`, so the route layer stays thin — it just maps the
result onto an HTTP response.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from fastapi.concurrency import run_in_threadpool

from hybrid_orchestration.codebase_parser import parse_codebase
from hybrid_orchestration.diff_engine import DiffResult, run_diff_engine
from hybrid_orchestration.surgical_agent import resolve_ambiguous
from ingestion_layer.repo_cache.clone_repo import CloneResult, clone_repo
from ingestion_layer.utils.db_utils import has_active_graph

logger = logging.getLogger("meridian.repo_actions")

Mode = Literal["FULL", "PATCH"]


@dataclass(frozen=True)
class IngestionResult:
    repo_url: str
    branch: str
    mode: Mode
    clone: CloneResult | None  # populated when mode == "FULL"
    diff: DiffResult | None  # populated once the build pipeline runs
    # patch: PatchResult | None — populated when mode == "PATCH" (TODO when MCP lands)


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
            diff=None,
        )

    logger.info(
        "repo_actions: no active graph for %s@%s — FULL mode",
        repo_url,
        branch_name,
    )
    clone_result = await clone_repo(repo_url, pat, branch=branch)
    diff = await _run_full_pipeline(clone_result.repo)
    return IngestionResult(
        repo_url=repo_url,
        branch=branch_name,
        mode="FULL",
        clone=clone_result,
        diff=diff,
    )


async def _run_full_pipeline(repo: str) -> DiffResult:
    """C5 (parse) → C6 (resolve) → C7 (diff engine) for a freshly cloned repo.

    C5 is CPU-bound tree-sitter work, so it runs off the event loop. C6 and
    C7 are async-native and run inline.
    """
    parse_result = await run_in_threadpool(parse_codebase, repo)
    parse_result = await resolve_ambiguous(parse_result)
    return run_diff_engine(parse_result)


async def _mcp_incremental_sync(repo_url: str, pat: str, branch: str) -> None:
    """Template — incremental sync via `git pull` + GitHub MCP enrichment.

    TODO(C7):
      1. `git pull` in the existing cache (subprocess, NOT MCP).
      2. `git diff <last_sha>..HEAD --name-status -M` → FileDiff.
      3. GitHub MCP `compare_commits` for PR/issue context on changed files.
      4. Return PatchResult(file_diff, enrichment, previous_sha, current_sha).
    """
    logger.info(
        "repo_actions: MCP incremental sync not yet implemented "
        "(repo=%s branch=%s)",
        repo_url,
        branch,
    )
    return None
