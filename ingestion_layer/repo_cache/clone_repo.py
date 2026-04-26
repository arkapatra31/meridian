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

logger = logging.getLogger("meridian.repo_cache")

# Configurable via the CACHE_ROOT env var; falls back to repo_cache/codebase/.
_DEFAULT_CACHE_ROOT = Path(__file__).resolve().parent / "codebase"


def _cache_root() -> Path:
    return Path(os.environ.get("CACHE_ROOT") or _DEFAULT_CACHE_ROOT).expanduser()


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

    cache_root = _cache_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    dest = cache_root / repo

    if dest.exists():
        logger.info("repo_cache: clone already exists at %s — skipping", dest)
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
