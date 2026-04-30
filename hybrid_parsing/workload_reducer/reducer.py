"""Pass 1.5 — Symbol-index workload reducer (entry point).

Sits between C4a (tree-sitter) and C4b (agent resolver). Detects the source
language of each AmbiguousRef and routes it to the appropriate language-specific
reducer. Unrecognised languages fall back to generic reduction.

Typical outcome for a mixed repo:
  ~88% dropped  (external/stdlib symbols with no project match)
  ~10% resolved (unique cross-file refs resolved from the symbol index)
  ~2%  passed   (genuine collisions deferred to C4b)
"""

from __future__ import annotations

import logging
from collections import defaultdict

from ..codebase_parser.models import AmbiguousRef, Edge, ParseResult
from .reducer_java import reduce_java_refs
from .reducer_javascript import reduce_javascript_refs
from .reducer_python import reduce_python_refs

logger = logging.getLogger("meridian.workload_reducer")

# Maps file extension → language key
_EXT_TO_LANG: dict[str, str] = {
    ".py":  "python",
    ".java": "java",
    ".js":  "javascript",
    ".jsx": "javascript",
    ".ts":  "javascript",
    ".tsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}

_KIND_TO_EDGE: dict[str, str] = {
    "import": "IMPORTS",
    "call": "CALLS",
    "decorator": "DECORATES",
    "inherits": "INHERITS",
}


def reduce_workload(parse_result: ParseResult) -> ParseResult:
    """Route each AmbiguousRef to its language reducer; mutate parse_result in place.

    - Appends INFERRED edges for resolved refs.
    - Replaces `ambiguous` with only the refs that still need agent reasoning.
    """
    if not parse_result.ambiguous:
        return parse_result

    name_index = _build_name_index(parse_result)
    total_before = len(parse_result.ambiguous)

    # Partition refs by source language
    by_lang: dict[str, list[AmbiguousRef]] = defaultdict(list)
    for ref in parse_result.ambiguous:
        ext = "." + ref.file.rsplit(".", 1)[-1] if "." in ref.file else ""
        by_lang[_EXT_TO_LANG.get(ext, "generic")].append(ref)

    all_edges: list[Edge] = []
    all_remaining: list[AmbiguousRef] = []

    # Language-specific reducers
    if by_lang["python"]:
        edges, rem = reduce_python_refs(by_lang["python"], name_index)
        all_edges.extend(edges)
        all_remaining.extend(rem)

    if by_lang["java"]:
        edges, rem = reduce_java_refs(by_lang["java"], name_index)
        all_edges.extend(edges)
        all_remaining.extend(rem)

    if by_lang["javascript"]:
        edges, rem = reduce_javascript_refs(by_lang["javascript"], name_index)
        all_edges.extend(edges)
        all_remaining.extend(rem)

    # Generic fallback for all other languages
    if by_lang["generic"]:
        edges, rem = _reduce_generic(by_lang["generic"], name_index)
        all_edges.extend(edges)
        all_remaining.extend(rem)

    parse_result.edges.extend(all_edges)
    parse_result.ambiguous = all_remaining

    resolved = len(all_edges)
    passed = len(all_remaining)
    dropped = total_before - resolved - passed
    logger.info(
        "workload_reducer: %d total — dropped %d (%.0f%%)  resolved %d (%.0f%%)  passed_to_agent %d (%.0f%%)",
        total_before,
        dropped, 100 * dropped / max(1, total_before),
        resolved, 100 * resolved / max(1, total_before),
        passed, 100 * passed / max(1, total_before),
    )
    return parse_result


# ---------------------------------------------------------------------------
# Generic fallback (languages without a dedicated reducer)
# ---------------------------------------------------------------------------

def _reduce_generic(
    refs: list[AmbiguousRef],
    name_index: dict[str, list[str]],
) -> tuple[list[Edge], list[AmbiguousRef]]:
    """Best-effort reduction for languages without a dedicated reducer."""
    new_edges: list[Edge] = []
    remaining: list[AmbiguousRef] = []

    for ref in refs:
        name = _extract_generic_symbol_name(ref)
        if not name:
            continue

        candidates = name_index.get(name, [])
        if not candidates:
            continue

        target: str | None = None
        if len(candidates) == 1:
            target = candidates[0]
        elif ref.kind in ("import", "inherits", "decorator"):
            target = _same_package_heuristic(ref.source, candidates)

        if target is not None:
            edge_type = _KIND_TO_EDGE.get(ref.kind)
            if edge_type:
                new_edges.append(
                    Edge(
                        source=ref.source,
                        target=target,
                        type=edge_type,
                        confidence="INFERRED",
                        metadata={"reasoning": "symbol_index: unique match", "raw": ref.raw},
                    )
                )
        else:
            remaining.append(ref)

    return new_edges, remaining


def _extract_generic_symbol_name(ref: AmbiguousRef) -> str:
    raw = ref.raw.strip()
    if ref.kind == "import":
        return raw.rsplit(".", 1)[-1].rstrip(";").strip()
    if ref.kind in ("inherits", "decorator"):
        return raw.split("<")[0].split("[")[0].strip()
    if ref.kind == "call":
        return raw.rsplit(".", 1)[-1].split("(")[0].strip()
    return raw


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _build_name_index(parse_result: ParseResult) -> dict[str, list[str]]:
    """Map each node's simple name → [node_id, ...]."""
    index: dict[str, list[str]] = defaultdict(list)
    for node in parse_result.nodes:
        if node.name:
            index[node.name].append(node.id)
    return dict(index)


def _same_package_heuristic(source_id: str, candidates: list[str]) -> str | None:
    """Pick the single candidate closest to the source file, or None."""
    source_file = source_id.split("::")[0] if "::" in source_id else source_id
    source_dir = source_file.rsplit("/", 1)[0] if "/" in source_file else ""

    same = [
        c for c in candidates
        if _file_of(c).startswith(source_dir + "/") or _file_of(c) == source_file
    ]
    if len(same) == 1:
        return same[0]

    if "/" in source_dir:
        parent = source_dir.rsplit("/", 1)[0]
        parent_matches = [c for c in candidates if _file_of(c).startswith(parent + "/")]
        if len(parent_matches) == 1:
            return parent_matches[0]

    return None


def _file_of(node_id: str) -> str:
    return node_id.split("::")[0] if "::" in node_id else node_id
