"""Shared filesystem / path helpers for the ingestion layer."""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_CACHE_ROOT = (
    Path(__file__).resolve().parent.parent / "repo_cache" / "codebase"
)


def cache_root() -> Path:
    """Resolve the on-disk repo cache root, honoring the CACHE_ROOT env var."""
    return Path(os.environ.get("CACHE_ROOT") or _DEFAULT_CACHE_ROOT).expanduser()
