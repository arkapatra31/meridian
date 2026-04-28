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
from ingestion_layer.utils.utils import cache_root

logger = logging.getLogger("meridian.repo_cache")


@dataclass(frozen=True)
class CloneResult:
    repo_id: str
    owner: str
    repo: str
    branch: str | None
    path: Path
    last_commit_sha: str


async def clone_repo(
    repo_url: str,
    pat: str,
    branch: str | None = None,
) -> CloneResult:
    """Clone `repo_url` into `<CACHE_ROOT>/<repo>`.

    Caller is the ingestion dispatcher, which only routes here when no active
    graph exists. A leftover cache dir from an aborted prior run is wiped
    before cloning — git would otherwise refuse with "destination exists".
    The wipe is gated on (a) the path being inside the cache root and (b) the
    dir actually being a git clone, so a stray non-git directory surfaces an
    error instead of being silently destroyed.
    """
    owner, repo = parse_owner_repo(repo_url)
    rid = repo_id(repo_url)

    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / repo

    if dest.exists():
        resolved = dest.resolve()
        if root.resolve() not in resolved.parents:
            raise CloneError(
                f"refusing to delete path outside cache root: {resolved}"
            )
        if not (dest / ".git").exists():
            raise CloneError(
                f"cache dir exists but isn't a git clone: {dest}"
            )
        logger.info("repo_cache: clearing stale clone at %s", dest)
        await asyncio.to_thread(shutil.rmtree, dest, ignore_errors=True)

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

    head_sha = await _read_head_sha(dest)

    logger.info(
        "repo_cache: cloned %s/%s to %s (HEAD=%s)", owner, repo, dest, head_sha[:8]
    )
    return CloneResult(rid, owner, repo, branch, dest, head_sha)


async def _read_head_sha(repo_dir: Path) -> str:
    """Run `git rev-parse HEAD` in the freshly cloned dir."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo_dir),
        "rev-parse",
        "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise CloneError(
            f"git rev-parse HEAD failed (exit {proc.returncode}): "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )
    return stdout.decode("ascii").strip()


class CloneError(RuntimeError):
    """Raised when `git clone` fails."""
