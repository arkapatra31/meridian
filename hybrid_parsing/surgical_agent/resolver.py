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
import logging
import time

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
from .utils import (
    _Progress,
    _Stats,
    _chunk,
    _dedup,
    _parse_resolutions,
    _stringify_tool_result,
    _summarize_tool_input,
    _truncate,
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
CHUNK_SIZE = 30
# Concurrent orchestrator calls. Bound by Anthropic concurrency, not CPU.
MAX_CONCURRENT_CHUNKS = 10
# Seconds before a single chunk is cancelled and treated as empty. Prevents
# one hung orchestrator call from stalling the entire gather.
CHUNK_TIMEOUT_S = 300

# Set to True for full per-subagent log lines; False for a single dynamic
# progress bar written to stderr instead.
SUBAGENT_VERBOSITY: bool = False


def _researcher_definition() -> AgentDefinition:
    return AgentDefinition(
        description="Read-only repo researcher. Resolves a single ambiguous "
        "code reference to a concrete graph node ID using Grep/Glob/Read.",
        prompt=RESEARCHER_PROMPT,
        tools=["Read", "Grep", "Glob"],
        model="haiku",
        effort="medium",
        maxTurns=1
    )


async def resolve_ambiguous(parse_result: ParseResult) -> ParseResult:
    """Augment `parse_result` with INFERRED edges from the Agent SDK."""
    if not parse_result.ambiguous:
        return parse_result

    repo_root = resolve_repo_path(parse_result.repo)
    # Fresh instance per call — not the singleton used by C2. Haiku is sufficient
    # for dispatch-and-aggregate work; max_turns=5 guarantees the model gets a
    # turn to emit JSON after tool results return (dispatch=1 + results=1 + aggregate=1).
    agent = ClaudeCodeAgent.get_instance(
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        allowed_tools=["Agent"],
        cwd=str(repo_root),
        agents={"researcher": _researcher_definition()},
        model="haiku",
        max_turns=5,
        name="surgical_agent",
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
    chunks = list(_chunk(unique_refs, CHUNK_SIZE))
    sem = asyncio.Semaphore(MAX_CONCURRENT_CHUNKS)
    progress = _Progress(len(unique_refs), len(chunks)) if not SUBAGENT_VERBOSITY else None
    stats = _Stats()
    wall_start = time.monotonic()

    async def run_chunk(chunk_idx: int, chunk: list[tuple[int, AmbiguousRef]]) -> dict[int, dict]:
        async with sem:
            if progress is not None:
                await progress.chunk_start(chunk_idx)
            timed_out = False
            try:
                result = await asyncio.wait_for(
                    _resolve_chunk(agent, chunk_idx, chunk, progress, stats),
                    timeout=CHUNK_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                timed_out = True
                result = {}

            n_picked = len(chunk)
            n_resolved = len(result)
            n_dropped = n_picked - n_resolved

            if timed_out:
                logger.warning(
                    "surgical_agent: sub-agent %d — %d nodes picked — timed out after %ds",
                    chunk_idx + 1, n_picked, CHUNK_TIMEOUT_S,
                )
            else:
                logger.info(
                    "surgical_agent: sub-agent %d — %d nodes picked — resolved %d / dropped %d",
                    chunk_idx + 1, n_picked, n_resolved, n_dropped,
                )

            if progress is not None:
                await progress.chunk_done(chunk_idx, n_picked)
            return result

    chunk_results = await asyncio.gather(
        *[run_chunk(i, c) for i, c in enumerate(chunks)]
    )
    if progress is not None:
        progress.finish()

    total_unique_resolved = sum(len(r) for r in chunk_results)
    remaining_unique = len(unique_refs) - total_unique_resolved
    logger.info(
        "surgical_agent: remaining %d/%d nodes unresolved",
        remaining_unique, len(unique_refs),
    )

    wall_s = time.monotonic() - wall_start
    logger.info(
        "surgical_agent: DONE  wall=%.1fs  api_time=%.1fs  cost=$%.4f",
        wall_s,
        stats.api_ms / 1000,
        stats.cost_usd,
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


async def _resolve_chunk(
    agent: ClaudeCodeAgent,
    chunk_idx: int,
    chunk: list[tuple[int, AmbiguousRef]],
    progress: _Progress | None = None,
    stats: _Stats | None = None,
) -> dict[int, dict]:
    """Run one orchestrator call for a chunk of unique refs.

    `chunk` items are (unique_index, AmbiguousRef). Returns
    {unique_index: {target, reasoning}} for refs with a non-null target.
    Refs the agent cannot resolve are dropped — no retry, no fallback.
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
    prompt = build_orchestrator_prompt(indexed)
    text = await _run_agent(agent, prompt, chunk_idx, stats)
    resolutions = _parse_resolutions(text)
    if resolutions is None:
        logger.warning(
            "surgical_agent: chunk %d returned no parseable JSON — dropping %d refs",
            chunk_idx, len(chunk),
        )
        return {}

    out: dict[int, dict] = {}
    by_index = {item.get("ref_index"): item for item in resolutions}
    for batch_i, (uidx, _) in enumerate(chunk):
        item = by_index.get(batch_i)
        # Only keep entries with a concrete non-null target — null means unresolvable, drop it.
        if item and item.get("target"):
            out[uidx] = item
    if SUBAGENT_VERBOSITY:
        logger.info(
            "surgical_agent: chunk %d resolved %d/%d", chunk_idx, len(out), len(chunk)
        )
    return out


async def _run_agent(
    agent: ClaudeCodeAgent,
    prompt: str,
    chunk_idx: int,
    stats: _Stats | None = None,
) -> str:
    """Drain orchestrator stream — logs every block when SUBAGENT_VERBOSITY=True."""
    parts: list[str] = []
    tag = f"chunk={chunk_idx}"
    async for msg in agent.run(prompt):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    text = block.text.strip()
                    if text:
                        parts.append(block.text)
                        if SUBAGENT_VERBOSITY:
                            logger.debug("[%s] orch.text: %s", tag, _truncate(text, 400))
                elif isinstance(block, ThinkingBlock):
                    if SUBAGENT_VERBOSITY:
                        logger.debug(
                            "[%s] orch.thinking: %s",
                            tag, _truncate(block.thinking, 400),
                        )
                elif isinstance(block, ToolUseBlock):
                    if SUBAGENT_VERBOSITY:
                        logger.info(
                            "[%s] dispatch %s id=%s input=%s",
                            tag, block.name, block.id, _summarize_tool_input(block.input),
                        )
        elif isinstance(msg, UserMessage):
            # Tool results stream back as user messages.
            content = msg.content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, ToolResultBlock) and SUBAGENT_VERBOSITY:
                        logger.info(
                            "[%s] result id=%s err=%s body=%s",
                            tag, block.tool_use_id, bool(block.is_error),
                            _truncate(_stringify_tool_result(block.content), 600),
                        )
        elif isinstance(msg, ResultMessage):
            if stats is not None:
                stats.record(msg)
            break
    return "".join(parts)
