"""PATCH (incremental sync) pipeline.

Skeleton — see TODOs below. Invoked by `orchestrator.sync_repo` when an
active graph already exists for `(repo_url, branch)`.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("meridian.orchestrator.patch_build")


async def patch_sync(repo_url: str, pat: str, branch: str) -> None:
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
