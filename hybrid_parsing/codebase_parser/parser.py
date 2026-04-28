"""Pass 1 entry point — `parse_codebase(repo)`.

Walks `<CACHE_ROOT>/<repo>/`, dispatches each source file to its language walker,
and aggregates the results into a single `ParseResult`.

`CACHE_ROOT` resolution matches `ingestion_layer.repo_cache.clone_repo` so this
reads exactly what was cloned.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from pathlib import Path

from .languages import detect_language
from .models import AmbiguousRef, Edge, Node, ParseResult
from .walkers import parse_java, parse_javascript, parse_tsx, parse_typescript, parse_python

logger = logging.getLogger("meridian.codebase_parser")

# Same default as ingestion_layer/repo_cache/clone_repo.py.
_DEFAULT_CACHE_ROOT = (
    Path(__file__).resolve().parents[2] / "ingestion_layer" / "repo_cache" / "codebase"
)

# Skip dirs we never want to parse — VCS, build outputs, package stores, caches.
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "target",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".ruff_cache",
        ".gradle",
        ".idea",
        ".vscode",
        "out",
        "bin",
        "obj",
    }
)

# Skip files larger than this — generated/minified blobs blow up parse time
# without producing useful graph data.
_MAX_FILE_BYTES = 1_000_000

WalkerFn = Callable[
    [str, bytes, Path], tuple[list[Node], list[Edge], list[AmbiguousRef]]
]

WALKERS: dict[str, WalkerFn] = {
    "python": parse_python,
    "java": parse_java,
    "javascript": parse_javascript,
    "typescript": parse_typescript,
    "tsx": parse_tsx,
}


def cache_root() -> Path:
    return Path(os.environ.get("CACHE_ROOT") or _DEFAULT_CACHE_ROOT).expanduser()


def resolve_repo_path(repo: str) -> Path:
    if not repo or "/" in repo or "\\" in repo or repo in (".", ".."):
        raise ValueError(f"Invalid repo name: {repo!r}")
    path = (cache_root() / repo).resolve()
    root = cache_root().resolve()
    if root not in path.parents and path != root:
        raise ValueError(f"Repo path escapes cache root: {repo!r}")
    if not path.is_dir():
        raise FileNotFoundError(f"Repo not found in cache: {path}")
    return path


def parse_codebase(repo: str) -> ParseResult:
    """Parse every supported source file under `<CACHE_ROOT>/<repo>/`."""
    root = resolve_repo_path(repo)
    result = ParseResult(repo=repo, root=str(root))

    for path in _iter_source_files(root):
        _parse_one_file(path, root, result)

    logger.info(
        "codebase_parser: %s parsed=%d skipped=%d nodes=%d edges=%d ambiguous=%d",
        repo,
        result.files_parsed,
        result.files_skipped,
        len(result.nodes),
        len(result.edges),
        len(result.ambiguous),
    )
    return result


def parse_files(repo: str, files: list[str]) -> ParseResult:
    """Parse only the given files (relative POSIX paths under the repo root).

    Used by the PATCH path: takes the `added ∪ modified ∪ renamed-to` set
    from `git diff` and runs the same per-file walker dispatch as
    `parse_codebase`, just over an explicit list. Missing or unsupported
    files are counted as skipped, not raised — same contract as the
    directory walk.
    """
    root = resolve_repo_path(repo)
    result = ParseResult(repo=repo, root=str(root))

    for rel in files:
        path = (root / rel).resolve()
        # Reject paths that escape the repo root (e.g. `../foo`); also catches
        # absolute paths someone fed in by mistake.
        if root not in path.parents and path != root:
            result.errors.append(f"{rel}: refused (escapes repo root)")
            result.files_skipped += 1
            continue
        if not path.is_file():
            # Includes the deletion-race case — caller should feed only
            # `added ∪ modified ∪ renamed-to`, but a file may still be gone.
            result.files_skipped += 1
            continue
        _parse_one_file(path, root, result)

    logger.info(
        "codebase_parser: %s (delta) parsed=%d skipped=%d nodes=%d edges=%d ambiguous=%d",
        repo,
        result.files_parsed,
        result.files_skipped,
        len(result.nodes),
        len(result.edges),
        len(result.ambiguous),
    )
    return result


def _parse_one_file(path: Path, root: Path, result: ParseResult) -> None:
    """Dispatch a single file through its language walker. Mutates `result`."""
    rel = path.relative_to(root).as_posix()
    lang = detect_language(path)
    if lang is None:
        result.files_skipped += 1
        return

    walker = WALKERS.get(lang)
    if walker is None:
        # Recognized extension, no walker yet — count as skipped, not an error.
        result.files_skipped += 1
        return

    try:
        stat = path.stat()
    except OSError as exc:
        result.errors.append(f"{rel}: stat failed — {exc}")
        result.files_skipped += 1
        return
    if stat.st_size > _MAX_FILE_BYTES:
        result.files_skipped += 1
        return

    try:
        source = path.read_bytes()
    except OSError as exc:
        result.errors.append(f"{rel}: read failed — {exc}")
        result.files_skipped += 1
        return

    try:
        nodes, edges, ambiguous = walker(rel, source, root)
    except Exception as exc:  # tree-sitter / walker bug — don't kill the run
        logger.exception("parse failed for %s", rel)
        result.errors.append(f"{rel}: parse failed — {exc}")
        result.files_skipped += 1
        return

    result.nodes.extend(nodes)
    result.edges.extend(edges)
    result.ambiguous.extend(ambiguous)
    result.files_parsed += 1
    result.languages[lang] = result.languages.get(lang, 0) + 1


def _iter_source_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            if fname.startswith("."):
                continue
            yield Path(dirpath) / fname
