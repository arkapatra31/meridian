"""Clone a GitHub repository into the local repo cache via the git protocol.

Uses `git clone` as a subprocess (NOT the GitHub REST API / MCP). This avoids
the 5,000 req/hr REST rate limit — git's smart transfer protocol is unmetered.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ingestion_layer.github_mcp.helpers import parse_owner_repo, repo_id
from ingestion_layer.utils.db_utils import has_active_graph
from ingestion_layer.utils.utils import cache_root

logger = logging.getLogger("meridian.repo_cache")


@dataclass(frozen=True)
class CloneResult:
    repo_id: str
    owner: str
    repo: str
    branch: str | None
    path: Path
    reused: bool


async def clone_repo(
    repo_url: str,
    pat: str,
    branch: str | None = None,
) -> CloneResult:
    """Clone `repo_url` into `<CACHE_ROOT>/<repo>`.

    If the destination already exists, the existing clone is reused — re-cloning
    the same repo is wasted work; use the sync flow when you need updates.
    """
    owner, repo = parse_owner_repo(repo_url)
    rid = repo_id(repo_url)

    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / repo

    if await asyncio.to_thread(has_active_graph, repo_url, branch or "main"):
        logger.info(
            "repo_cache: active graph already exists for %s@%s — skipping clone",
            repo_url,
            branch or "main",
        )
        return CloneResult(rid, owner, repo, branch, dest, reused=True)

    # Authenticated HTTPS URL form GitHub accepts for PAT auth.
    auth_url = f"https://x-access-token:{pat}@github.com/{owner}/{repo}.git"

    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch, "--single-branch"]
    cmd += [auth_url, str(dest)]

    # Avoid leaking the PAT via subprocess error messages or interactive prompts.
    env = {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/true",
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    }

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        # Strip the PAT from any echoed URL before surfacing the error.
        msg = stderr.decode("utf-8", errors="replace").replace(pat, "***")
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise CloneError(f"git clone failed (exit {proc.returncode}): {msg.strip()}")

    logger.info("repo_cache: cloned %s/%s to %s", owner, repo, dest)
    return CloneResult(rid, owner, repo, branch, dest, reused=False)


class CloneError(RuntimeError):
    """Raised when `git clone` fails."""
