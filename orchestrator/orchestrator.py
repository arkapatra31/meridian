"""C2 — Agent SDK Orchestrator.

Single entry point that drives the full Meridian pipeline. Decides FULL vs
PATCH based on whether a READY graph already exists for `(repo_url, branch)`,
then chains the appropriate stages:

    FULL:   see `full_build.py` — clone → C4a → C4b → C4c → C5a → C5b →
            link tree → audit row.

    PATCH:  see `patch_build.py` — git pull → diff → re-run C4a/C4b on
            changed files → mutate stored tree → re-run C5a → re-cluster
            affected communities → persist. (Skeleton only.)

The ingestion layer below is intentionally dumb: it exposes `clone_repo`,
`persist_clone`, and (eventually) `pull_repo`/MCP enrichment. All decisions
about *what* to call live here.
"""

from __future__ import annotations

import asyncio
import logging

from orchestrator.utils.db_utils import has_active_graph

from .full_build import full_build
from .patch_build import patch_sync
from .types import OrchestrationResult

logger = logging.getLogger("meridian.orchestrator")


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
        await patch_sync(repo_url, pat, branch_name)
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
    return await full_build(repo_url, pat, branch)
