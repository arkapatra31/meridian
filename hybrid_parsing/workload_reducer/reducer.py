"""Pass 1.5 — Symbol-index workload reducer.

Sits between C4a (tree-sitter) and C4b (agent resolver). Classifies every
ambiguous ref into one of three buckets — no LLM, no filesystem access:

  0 node-index matches  → drop  (external / stdlib symbol, nothing to link)
  1 match               → resolve in Python (INFERRED edge, zero API cost)
  multiple matches      → same-package heuristic for import/inherits/decorator;
                          call refs with collisions pass straight to C4b

Typical outcome for Java Spring repos:
  ~88% dropped  (framework imports that slipped past Pass 1 prefix filters)
  ~10% resolved (unique cross-file class / interface references)
  ~2%  passed   (genuine naming collisions — methods named save/find/etc.)
"""

from __future__ import annotations

import logging
from collections import defaultdict

from ..codebase_parser.models import AmbiguousRef, Edge, ParseResult

logger = logging.getLogger("meridian.workload_reducer")

_KIND_TO_EDGE: dict[str, str] = {
    "import": "IMPORTS",
    "call": "CALLS",
    "decorator": "DECORATES",
    "inherits": "INHERITS",
}


def reduce_workload(parse_result: ParseResult) -> ParseResult:
    """Resolve unambiguous refs in Python; drop externals; pass collisions to C4b.

    Mutates `parse_result` in place (same contract as `resolve_ambiguous`):
      - Appends INFERRED edges for resolved refs.
      - Replaces `ambiguous` with only the refs that still need agent reasoning.
    """
    if not parse_result.ambiguous:
        return parse_result

    name_index = _build_name_index(parse_result)

    new_edges: list[Edge] = []
    remaining: list[AmbiguousRef] = []
    dropped = resolved = passed = 0

    for ref in parse_result.ambiguous:
        candidates = _find_candidates(ref, name_index)

        if not candidates:
            dropped += 1
            continue

        target: str | None = None

        if len(candidates) == 1:
            target = candidates[0]
        elif ref.kind in ("import", "inherits", "decorator"):
            # For non-call kinds, a same-package match is strong enough signal.
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
                        metadata={
                            "reasoning": (
                                "symbol_index: unique match"
                                if len(candidates) == 1
                                else "symbol_index: same-package heuristic"
                            ),
                            "raw": ref.raw,
                        },
                    )
                )
                resolved += 1
            else:
                dropped += 1
        else:
            remaining.append(ref)
            passed += 1

    parse_result.edges.extend(new_edges)
    parse_result.ambiguous = remaining

    total = dropped + resolved + passed
    logger.info(
        "workload_reducer: %d total — dropped %d (%.0f%%)  resolved %d (%.0f%%)  passed_to_agent %d (%.0f%%)",
        total,
        dropped, 100 * dropped / max(1, total),
        resolved, 100 * resolved / max(1, total),
        passed, 100 * passed / max(1, total),
    )
    return parse_result


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def _build_name_index(parse_result: ParseResult) -> dict[str, list[str]]:
    """Map each node's simple name → [node_id, ...]."""
    index: dict[str, list[str]] = defaultdict(list)
    for node in parse_result.nodes:
        if node.name:
            index[node.name].append(node.id)
    return dict(index)


# ---------------------------------------------------------------------------
# Candidate lookup
# ---------------------------------------------------------------------------

def _find_candidates(ref: AmbiguousRef, name_index: dict[str, list[str]]) -> list[str]:
    name = _extract_symbol_name(ref)
    if not name:
        return []
    return name_index.get(name, [])


def _extract_symbol_name(ref: AmbiguousRef) -> str:
    """Derive the simple lookup name from the raw ref text, by kind."""
    raw = ref.raw.strip()

    if ref.kind == "import":
        return _parse_import_name(raw)

    if ref.kind in ("inherits", "decorator"):
        # Strip generic / array notation: "BaseEntity<T>" → "BaseEntity"
        return raw.split("<")[0].split("[")[0].strip()

    if ref.kind == "call":
        # "userService.save" → "save";  "save" → "save";  strip parens if any
        return raw.rsplit(".", 1)[-1].split("(")[0].strip()

    return raw


def _parse_import_name(raw: str) -> str:
    """Extract the imported symbol name from any language's import syntax."""
    cleaned = raw.strip().rstrip(";").strip()

    # Python / TS / JS:  "from module import SomeClass [as Alias]"
    #                    "import { SomeClass } from './module'"
    if " import " in cleaned:
        imported_part = cleaned.split(" import ", 1)[1].strip()
        # Destructured TS/JS:  "{ SomeClass, Other }" → skip multi-import
        imported_part = imported_part.strip("{} ")
        names = [n.strip() for n in imported_part.split(",")]
        if len(names) > 1:
            return ""  # multi-name import → can't pick one, let C4b handle
        return names[0].split(" as ")[0].strip()

    # Java / Kotlin / Go:  "import com.example.service.UserService"
    parts = cleaned.split()
    if not parts:
        return ""
    dotted = parts[-1]

    # Wildcard: "import com.example.*" → unresolvable
    if dotted.endswith("*"):
        return ""

    return dotted.rsplit(".", 1)[-1]


# ---------------------------------------------------------------------------
# Same-package heuristic (for import / inherits / decorator collisions)
# ---------------------------------------------------------------------------

def _same_package_heuristic(source_id: str, candidates: list[str]) -> str | None:
    """Pick the single candidate closest to the source file, or None.

    Walks outward from exact directory → parent directory. Returns only if
    exactly one candidate matches at that level — never guesses between two.
    """
    source_file = source_id.split("::")[0] if "::" in source_id else source_id
    source_dir = source_file.rsplit("/", 1)[0] if "/" in source_file else ""

    same = [c for c in candidates if _file_of(c).startswith(source_dir + "/")
            or _file_of(c) == source_file]
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
