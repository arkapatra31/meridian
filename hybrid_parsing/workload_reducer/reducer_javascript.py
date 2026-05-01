"""JavaScript / TypeScript-specific workload reducer (Pass 1.5).

Handles AmbiguousRefs emitted by the JS/TS tree-sitter walker.
Covers .js, .jsx, .mjs, .cjs, .ts, .tsx files.
Entry point: reduce_javascript_refs(refs, name_index).
"""

from __future__ import annotations

import logging

from ..codebase_parser.models import AmbiguousRef, Edge

logger = logging.getLogger("meridian.workload_reducer.javascript")

_KIND_TO_EDGE: dict[str, str] = {
    "import": "IMPORTS",
    "call": "CALLS",
    "decorator": "DECORATES",
    "inherits": "INHERITS",
}

# Method names that are universally from built-in prototypes or the runtime —
# never project-level graph nodes worth deferring to C4b.
_JS_DROP_CALL_NAMES: frozenset[str] = frozenset({
    # Object.prototype (every JS object has these)
    "toString", "valueOf", "hasOwnProperty", "isPrototypeOf",
    "propertyIsEnumerable", "toLocaleString",
    # console (always the global console, never a project node)
    "log", "debug", "info", "warn", "error", "trace",
    "group", "groupEnd", "table", "assert", "clear", "count",
    "time", "timeEnd", "timeLog", "dir",
})


def reduce_javascript_refs(
    refs: list[AmbiguousRef],
    name_index: dict[str, list[str]],
) -> tuple[list[Edge], list[AmbiguousRef]]:
    """Resolve or drop JS/TS AmbiguousRefs using the symbol index.

    Returns (resolved_edges, remaining_refs_for_agent).
    """
    new_edges: list[Edge] = []
    remaining: list[AmbiguousRef] = []
    dropped = resolved = passed = 0

    for ref in refs:
        # Drop calls to universally-external method names before index lookup.
        if ref.kind == "call":
            call_name = _extract_call_name(ref.raw)
            if call_name in _JS_DROP_CALL_NAMES:
                dropped += 1
                continue

        name = _extract_symbol_name(ref)
        if not name:
            dropped += 1
            continue

        candidates = name_index.get(name, [])

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
        "javascript: %d total — dropped %d  resolved %d  passed %d",
        total, dropped, resolved, passed,
    )
    return new_edges, remaining


# ---------------------------------------------------------------------------
# Symbol name extraction (JS/TS-specific)
# ---------------------------------------------------------------------------

def _extract_symbol_name(ref: AmbiguousRef) -> str:
    """Derive the simple lookup name from the raw ref text (JS/TS-specific)."""
    raw = ref.raw.strip()

    if ref.kind == "import":
        return _parse_import_name(raw)

    if ref.kind in ("inherits", "decorator"):
        # TS generics: "BaseService<T>" → "BaseService"
        return raw.split("<")[0].split("[")[0].strip()

    if ref.kind == "call":
        return _extract_call_name(raw)

    return raw


def _parse_import_name(raw: str) -> str:
    """Extract the imported symbol name from JS/TS ESM import syntax.

    Examples:
      "import UserService from './services/user'"        → "UserService"
      "import { UserService } from './services/user'"    → "UserService"
      "import { A, B } from './utils'"                   → "" (multi, pass to agent)
      "import { UserService as US } from './services'"   → "UserService"
      "import * as Services from './services'"           → "" (namespace, pass to agent)
    """
    cleaned = raw.strip().rstrip(";").strip()

    # "import { ... } from '...'" or "import X from '...'"
    if " from " in cleaned:
        # Strip the " from '...'" part
        specifier_part = cleaned.split(" from ")[0].removeprefix("import").strip()

        # Namespace import: "* as NS" — unresolvable to a single symbol
        if specifier_part.startswith("*"):
            return ""

        # Named imports: "{ X }" or "{ X as Y }" or "{ X, Y }"
        if specifier_part.startswith("{"):
            inner = specifier_part.strip("{} ")
            names = [n.strip() for n in inner.split(",")]
            if len(names) > 1:
                return ""  # multi-named import — let C4b handle
            # "X as Alias" → take "X" (the original exported name)
            return names[0].split(" as ")[0].strip()

        # Default import: "UserService"
        return specifier_part.split(" as ")[0].strip()

    # Plain "import 'side-effect'" or unrecognised shape
    return ""


def _extract_call_name(raw: str) -> str:
    """Extract the method/function name from a JS/TS call expression.

    Examples:
      "this.userService"   → "userService"
      "service.findAll"    → "findAll"
      "handleSubmit"       → "handleSubmit"
    """
    name_part = raw.split("(")[0].strip()
    return name_part.rsplit(".", 1)[-1].strip()


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
