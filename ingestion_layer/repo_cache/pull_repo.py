"""Refresh an existing local clone via `git pull`, then surface the diff.

Used by the orchestrator's PATCH path. Mirrors `clone_repo.py` in shape:
subprocess git only, PAT scrubbed from any echoed URL, no shell expansion.
If the cache directory has been evicted (sliding TTL) we fall back to a
fresh `clone_repo` so the caller never has to branch.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from ingestion_layer.github_mcp.helpers import parse_owner_repo, repo_id
from ingestion_layer.utils.utils import cache_root

from .clone_repo import CloneError, clone_repo

logger = logging.getLogger("meridian.repo_cache.pull")


@dataclass(frozen=True)
class FileChange:
    status: str  # 'A' (added) | 'M' (modified) | 'D' (deleted) | 'R' (renamed)
    path: str  # current path (post-rename for 'R', or path of A/M/D entries)
    old_path: str | None = None  # populated only for 'R' entries


@dataclass(frozen=True)
class PullResult:
    repo_id: str
    owner: str
    repo: str
    branch: str | None
    path: Path
    previous_sha: str
    current_sha: str
    changed_files: list[FileChange]
    re_cloned: bool  # True if cache was evicted and we fell back to clone

    @property
    def has_changes(self) -> bool:
        return self.previous_sha != self.current_sha


async def pull_repo(
    repo_url: str,
    pat: str,
    branch: str | None,
    previous_sha: str,
) -> PullResult:
    """Pull `repo_url` and diff from `previous_sha` to the new HEAD.

    `previous_sha` is the orchestrator's anchor (from `repo_clones.last_commit_sha`)
    used both to detect no-op pulls and to compute the file-change set.
    """
    owner, repo = parse_owner_repo(repo_url)
    rid = repo_id(repo_url)
    dest = cache_root() / repo

    # Cache evicted (TTL or manual cleanup). Re-clone — we still want the
    # caller's diff payload, so we compute it against `previous_sha` after
    # the fresh clone lands. Same logic as a real pull from there.
    if not (dest / ".git").exists():
        logger.info(
            "repo_cache.pull: cache absent for %s/%s — re-cloning before diff",
            owner, repo,
        )
        clone = await clone_repo(repo_url, pat, branch=branch)
        current = clone.last_commit_sha
        changed = await _diff(dest, previous_sha, current) if previous_sha != current else []
        return PullResult(
            repo_id=clone.repo_id,
            owner=clone.owner,
            repo=clone.repo,
            branch=clone.branch,
            path=clone.path,
            previous_sha=previous_sha,
            current_sha=current,
            changed_files=changed,
            re_cloned=True,
        )

    # Inject the PAT only into the remote URL we use for this single pull;
    # don't persist it via `remote set-url`.
    auth_url = f"https://x-access-token:{pat}@github.com/{owner}/{repo}.git"
    cmd = ["git", "-C", str(dest), "pull", "--ff-only", auth_url]
    if branch:
        cmd.append(branch)

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
        msg = stderr.decode("utf-8", errors="replace").replace(pat, "***")
        raise PullError(f"git pull failed (exit {proc.returncode}): {msg.strip()}")

    current_sha = await _read_head_sha(dest)
    changed = (
        await _diff(dest, previous_sha, current_sha)
        if previous_sha != current_sha
        else []
    )

    logger.info(
        "repo_cache.pull: %s/%s pulled %s..%s (%d changed)",
        owner, repo, previous_sha[:8], current_sha[:8], len(changed),
    )

    return PullResult(
        repo_id=rid,
        owner=owner,
        repo=repo,
        branch=branch,
        path=dest,
        previous_sha=previous_sha,
        current_sha=current_sha,
        changed_files=changed,
        re_cloned=False,
    )


async def _read_head_sha(repo_dir: Path) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo_dir), "rev-parse", "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise PullError(
            f"git rev-parse HEAD failed (exit {proc.returncode}): "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )
    return stdout.decode("ascii").strip()


async def _diff(repo_dir: Path, base_sha: str, head_sha: str) -> list[FileChange]:
    """`git diff --name-status -M <base>..<head>` → parsed FileChange list."""
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo_dir),
        "diff", "--name-status", "-M",
        f"{base_sha}..{head_sha}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise PullError(
            f"git diff failed (exit {proc.returncode}): "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )

    out: list[FileChange] = []
    for raw in stdout.decode("utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        code = parts[0]
        # Renames are reported as 'R<similarity>\told\tnew' (e.g. 'R100').
        if code.startswith("R") and len(parts) >= 3:
            out.append(FileChange(status="R", path=parts[2], old_path=parts[1]))
        elif code in ("A", "M", "D") and len(parts) >= 2:
            out.append(FileChange(status=code, path=parts[1]))
        # Anything else (C copy, T type-change, U unmerged) — skip; they don't
        # change the parse-tree contract in any way our walkers care about.
    return out


class PullError(CloneError):
    """Raised when `git pull` or the post-pull diff fails."""
