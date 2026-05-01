"""Shared utilities for the surgical resolver — progress, stats, dedup, chunking, parsing."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass, field

from claude_agent_sdk import ResultMessage

from ..codebase_parser.models import AmbiguousRef


class _Progress:
    """Single-line dynamic progress bar written to stderr.
    Active only when SUBAGENT_VERBOSITY=False.
    """

    def __init__(self, total_refs: int, total_chunks: int) -> None:
        self.total_refs = total_refs
        self.total_chunks = total_chunks
        self._processed = 0
        self._active: set[int] = set()
        self._lock = asyncio.Lock()

    async def chunk_start(self, chunk_idx: int) -> None:
        async with self._lock:
            self._active.add(chunk_idx + 1)
            self._render()

    async def chunk_done(self, chunk_idx: int, n_processed: int) -> None:
        async with self._lock:
            self._processed += n_processed
            self._active.discard(chunk_idx + 1)
            self._render()

    def _render(self) -> None:
        remaining = self.total_refs - self._processed
        pct_done = int(100 * self._processed / max(1, self.total_refs))
        bar_len = 28
        filled = int(bar_len * pct_done / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        active_str = ",".join(str(c) for c in sorted(self._active)) or "—"
        line = (
            f"\r  [{bar}] {pct_done:3d}%"
            f"  remaining {remaining}/{self.total_refs}"
            f"  chunk [{active_str}/{self.total_chunks}]"
            f"    "
        )
        sys.stderr.write(line)
        sys.stderr.flush()

    def finish(self) -> None:
        sys.stderr.write("\n")
        sys.stderr.flush()


@dataclass
class _Stats:
    """Accumulates cost and API time across all concurrent chunk calls."""
    cost_usd: float = field(default=0.0)
    api_ms: int = field(default=0)

    def record(self, msg: ResultMessage) -> None:
        if msg.total_cost_usd is not None:
            self.cost_usd += msg.total_cost_usd
        self.api_ms += msg.duration_ms


def _dedup(
    refs: list[AmbiguousRef],
) -> tuple[list[AmbiguousRef], list[int]]:
    """Returns (unique_refs, original_index → unique_index)."""
    key_to_unique: dict[tuple, int] = {}
    unique_refs: list[AmbiguousRef] = []
    mapping: list[int] = []
    for ref in refs:
        key = (ref.file, ref.raw, ref.kind, ref.source)
        if key not in key_to_unique:
            key_to_unique[key] = len(unique_refs)
            unique_refs.append(ref)
        mapping.append(key_to_unique[key])
    return unique_refs, mapping


def _chunk(items: list, size: int) -> list[list]:
    out: list[list] = []
    for i in range(0, len(items), size):
        chunk = [(i + j, item) for j, item in enumerate(items[i : i + size])]
        out.append(chunk)
    return out


def _parse_resolutions(text: str) -> list[dict] | None:
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else None
    if payload is None:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None
        payload = text[start : end + 1]
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    return [d for d in data if isinstance(d, dict)]


def _summarize_tool_input(payload) -> str:
    try:
        return _truncate(json.dumps(payload, ensure_ascii=False), 300)
    except (TypeError, ValueError):
        return _truncate(str(payload), 300)


def _stringify_tool_result(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            text = getattr(block, "text", None)
            if text is not None:
                out.append(text)
            else:
                out.append(str(block))
        return "\n".join(out)
    return str(content)


def _truncate(s: str, n: int) -> str:
    s = s.replace("\n", " ⏎ ")
    return s if len(s) <= n else s[:n] + f"…[+{len(s) - n}]"
