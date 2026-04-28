"""C4b — Pass 2 surgical resolver.

Pipeline:
  1. Dedup: collapse `(file, raw, kind)` duplicates so we only resolve each
     unique ambiguous reference once, then fan the answer back out to every
     original AmbiguousRef.
  2. Chunk: split unique refs into small chunks (~CHUNK_SIZE each) and run
     N orchestrator calls concurrently via `asyncio.gather`. Each orchestrator
     in turn delegates one subagent per ref IN PARALLEL via the `Agent` tool.
  3. Logging: every assistant text, tool dispatch, and tool result from the
     orchestrator stream is logged at DEBUG so subagent reasoning is visible.

Output: the same `ParseResult` mutated in place — INFERRED edges appended,
resolved ambiguous refs dropped from `ambiguous`, unresolved kept.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from sdk import ClaudeCodeAgent

from ..codebase_parser.models import AmbiguousRef, Edge, ParseResult
from ..codebase_parser.parser import resolve_repo_path
from .prompts import (
    ORCHESTRATOR_SYSTEM_PROMPT,
    RESEARCHER_PROMPT,
    build_orchestrator_prompt,
)

logger = logging.getLogger("meridian.surgical_agent")

_KIND_TO_EDGE = {
    "import": "IMPORTS",
    "call": "CALLS",
    "decorator": "DECORATES",
    "inherits": "INHERITS",
}

# Refs per orchestrator call. Small enough that the orchestrator can fan all
# of them out as parallel Agent tool uses in one or two responses.
CHUNK_SIZE = 15
# Concurrent orchestrator calls. Bound by Anthropic concurrency, not CPU.
MAX_CONCURRENT_CHUNKS = 4


def _researcher_definition() -> AgentDefinition:
    return AgentDefinition(
        description="Read-only repo researcher. Resolves a single ambiguous "
        "code reference to a concrete graph node ID using Grep/Glob/Read.",
        prompt=RESEARCHER_PROMPT,
        tools=["Read", "Grep", "Glob"],
        model="haiku",
    )


async def resolve_ambiguous(parse_result: ParseResult) -> ParseResult:
    """Augment `parse_result` with INFERRED edges from the Agent SDK."""
    if not parse_result.ambiguous:
        return parse_result

    repo_root = resolve_repo_path(parse_result.repo)
    agent = ClaudeCodeAgent.get_instance(
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        allowed_tools=["Agent", "Read", "Grep", "Glob"],
        cwd=str(repo_root),
        agents={"researcher": _researcher_definition()},
    )

    # 1. Dedup: collapse identical (file, raw, kind, source) refs.
    unique_refs, ref_to_unique = _dedup(parse_result.ambiguous)
    logger.info(
        "surgical_agent: %d ambiguous → %d unique (%.0f%% dedup)",
        len(parse_result.ambiguous),
        len(unique_refs),
        100.0 * (1 - len(unique_refs) / max(1, len(parse_result.ambiguous))),
    )

    # 2. Chunk + fan out concurrently.
    candidate_ids = [n.id for n in parse_result.nodes]
    chunks = list(_chunk(unique_refs, CHUNK_SIZE))
    sem = asyncio.Semaphore(MAX_CONCURRENT_CHUNKS)

    async def run_chunk(chunk_idx: int, chunk: list[tuple[int, AmbiguousRef]]) -> dict[int, dict]:
        async with sem:
            logger.info(
                "surgical_agent: chunk %d/%d dispatching %d refs",
                chunk_idx + 1, len(chunks), len(chunk),
            )
            return await _resolve_chunk(agent, chunk_idx, chunk, candidate_ids)

    chunk_results = await asyncio.gather(
        *[run_chunk(i, c) for i, c in enumerate(chunks)]
    )

    # Merge: unique_index → resolution dict
    unique_resolutions: dict[int, dict] = {}
    for r in chunk_results:
        unique_resolutions.update(r)

    # 3. Fan dedup'd answers back to every original ambiguous ref.
    new_edges: list[Edge] = []
    resolved_indices: set[int] = set()
    for orig_i, ref in enumerate(parse_result.ambiguous):
        unique_i = ref_to_unique[orig_i]
        item = unique_resolutions.get(unique_i)
        if not item:
            continue
        target = item.get("target")
        if not target:
            continue
        edge_type = _KIND_TO_EDGE.get(ref.kind)
        if edge_type is None:
            continue
        new_edges.append(
            Edge(
                source=ref.source,
                target=target,
                type=edge_type,
                confidence="INFERRED",
                metadata={"reasoning": item.get("reasoning") or "", "raw": ref.raw},
            )
        )
        resolved_indices.add(orig_i)

    parse_result.edges.extend(new_edges)
    parse_result.ambiguous = [
        r for i, r in enumerate(parse_result.ambiguous) if i not in resolved_indices
    ]

    logger.info(
        "surgical_agent: resolved=%d remaining_ambiguous=%d",
        len(new_edges),
        len(parse_result.ambiguous),
    )
    return parse_result


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


async def _resolve_chunk(
    agent: ClaudeCodeAgent,
    chunk_idx: int,
    chunk: list[tuple[int, AmbiguousRef]],
    candidate_ids: list[str],
) -> dict[int, dict]:
    """Run one orchestrator call for a chunk of unique refs.

    `chunk` items are (unique_index, AmbiguousRef). Returns
    {unique_index: {target, reasoning}} for resolved entries.
    """
    indexed = [
        {
            "index": batch_i,
            "file": r.file,
            "line": r.line,
            "kind": r.kind,
            "raw": r.raw,
            "source": r.source,
        }
        for batch_i, (_, r) in enumerate(chunk)
    ]
    prompt = build_orchestrator_prompt(indexed, candidate_ids)
    text = await _run_agent(agent, prompt, chunk_idx)
    resolutions = _parse_resolutions(text)
    if resolutions is None:
        logger.warning(
            "surgical_agent: chunk %d returned no parseable JSON", chunk_idx
        )
        return {}

    out: dict[int, dict] = {}
    by_index = {item.get("ref_index"): item for item in resolutions}
    for batch_i, (uidx, _) in enumerate(chunk):
        item = by_index.get(batch_i)
        if item:
            out[uidx] = item
    logger.info(
        "surgical_agent: chunk %d resolved %d/%d", chunk_idx, len(out), len(chunk)
    )
    return out


async def _run_agent(agent: ClaudeCodeAgent, prompt: str, chunk_idx: int) -> str:
    """Drain orchestrator stream. Logs every block so subagent activity is
    visible — text (reasoning), tool dispatches (subagent input), tool results
    (subagent output).
    """
    parts: list[str] = []
    tag = f"chunk={chunk_idx}"
    async for msg in agent.run(prompt):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    text = block.text.strip()
                    if text:
                        parts.append(block.text)
                        logger.debug("[%s] orch.text: %s", tag, _truncate(text, 400))
                elif isinstance(block, ThinkingBlock):
                    logger.debug(
                        "[%s] orch.thinking: %s",
                        tag, _truncate(block.thinking, 400),
                    )
                elif isinstance(block, ToolUseBlock):
                    logger.info(
                        "[%s] dispatch %s id=%s input=%s",
                        tag, block.name, block.id, _summarize_tool_input(block.input),
                    )
        elif isinstance(msg, UserMessage):
            # Tool results stream back as user messages.
            content = msg.content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, ToolResultBlock):
                        logger.info(
                            "[%s] result id=%s err=%s body=%s",
                            tag, block.tool_use_id, bool(block.is_error),
                            _truncate(_stringify_tool_result(block.content), 600),
                        )
        elif isinstance(msg, ResultMessage):
            break
    return "".join(parts)


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


def _chunk(items: list, size: int):
    out: list[list] = []
    for i in range(0, len(items), size):
        chunk = [(i + j, item) for j, item in enumerate(items[i : i + size])]
        out.append(chunk)
    return out
