"""Python-specific workload reducer (Pass 1.5).

Handles AmbiguousRefs emitted by the Python tree-sitter walker.
Entry point: reduce_python_refs(refs, name_index).
"""

from __future__ import annotations

import logging

from ..codebase_parser.models import AmbiguousRef, Edge

logger = logging.getLogger("meridian.workload_reducer.python")

_KIND_TO_EDGE: dict[str, str] = {
    "import": "IMPORTS",
    "call": "CALLS",
    "decorator": "DECORATES",
    "inherits": "INHERITS",
}


def reduce_python_refs(
    refs: list[AmbiguousRef],
    name_index: dict[str, list[str]],
) -> tuple[list[Edge], list[AmbiguousRef]]:
    """Resolve or drop Python AmbiguousRefs using the symbol index.

    Returns (resolved_edges, remaining_refs_for_agent).
    """
    new_edges: list[Edge] = []
    remaining: list[AmbiguousRef] = []
    dropped = resolved = passed = 0

    for ref in refs:
        candidates = _find_candidates(ref, name_index)

        if not candidates:
            dropped += 1
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

    total = dropped + resolved + passed
    logger.debug(
        "python: %d total — dropped %d  resolved %d  passed %d",
        total, dropped, resolved, passed,
    )
    return new_edges, remaining


# ---------------------------------------------------------------------------
# Symbol name extraction (Python-specific)
# ---------------------------------------------------------------------------

def _find_candidates(ref: AmbiguousRef, name_index: dict[str, list[str]]) -> list[str]:
    name = _extract_symbol_name(ref)
    if not name:
        return []
    return name_index.get(name, [])


def _extract_symbol_name(ref: AmbiguousRef) -> str:
    """Derive the simple lookup name from the raw ref text."""
    raw = ref.raw.strip()

    if ref.kind == "import":
        return _parse_import_name(raw)

    if ref.kind in ("inherits", "decorator"):
        return raw.split("<")[0].split("[")[0].strip()

    if ref.kind == "call":
        # "module.func" → "func";  "func" → "func"
        return raw.rsplit(".", 1)[-1].split("(")[0].strip()

    return raw


def _parse_import_name(raw: str) -> str:
    """Extract the imported symbol name from Python import syntax.

    Examples:
      "from .services import UserService"           → "UserService"
      "from services import UserService as US"      → "UserService"
      "from services import UserService, OrderSvc"  → "" (multi-import, pass to agent)
      "import services.user"                        → "user"
    """
    cleaned = raw.strip().rstrip(";").strip()

    # "from <module> import <names>" — Python / TS / JS style
    if " import " in cleaned:
        imported_part = cleaned.split(" import ", 1)[1].strip()
        imported_part = imported_part.strip("{} ")
        names = [n.strip() for n in imported_part.split(",")]
        if len(names) > 1:
            return ""  # multi-name import — can't pick one, let C4b handle
        return names[0].split(" as ")[0].strip()

    # "import a.b.c" — plain absolute import
    parts = cleaned.split()
    if not parts:
        return ""
    dotted = parts[-1]
    if dotted.endswith("*"):
        return ""
    return dotted.rsplit(".", 1)[-1]


# ---------------------------------------------------------------------------
# Shared heuristics
# ---------------------------------------------------------------------------

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
