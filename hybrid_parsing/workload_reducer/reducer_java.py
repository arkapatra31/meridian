"""Java-specific workload reducer (Pass 1.5).

Handles AmbiguousRefs emitted by the Java tree-sitter walker with
Java-specific drop rules for framework/stdlib method calls and imports.
Entry point: reduce_java_refs(refs, name_index).
"""

from __future__ import annotations

import logging

from ..codebase_parser.models import AmbiguousRef, Edge

logger = logging.getLogger("meridian.workload_reducer.java")

_KIND_TO_EDGE: dict[str, str] = {
    "import": "IMPORTS",
    "call": "CALLS",
    "decorator": "DECORATES",
    "inherits": "INHERITS",
}

# Method names that are universally from java.lang.Object, logging frameworks,
# or builder APIs — never project-level graph nodes worth deferring to C4b.
_JAVA_DROP_CALL_NAMES: frozenset[str] = frozenset({
    # java.lang.Object (every Java object has these)
    "toString", "hashCode", "equals", "compareTo", "clone", "finalize",
    "wait", "notify", "notifyAll", "getClass",
    # SLF4J / Log4j / java.util.logging — always on external Logger objects
    "debug", "info", "warn", "error", "trace", "fatal",
    "isDebugEnabled", "isInfoEnabled", "isWarnEnabled", "isErrorEnabled",
    # Lombok/protobuf/Spring builder terminal
    "build",
    # Spring Data JPA / CrudRepository / JpaRepository — virtually always
    # called on an external Repository<T> proxy, never project nodes.
    "save", "saveAll", "saveAndFlush", "saveAllAndFlush",
    "findById", "findAll", "findAllById", "findOne",
    "deleteById", "delete", "deleteAll", "deleteAllById", "deleteAllInBatch",
    "existsById", "count", "flush",
    "getOne", "getById", "getReferenceById",
})


def reduce_java_refs(
    refs: list[AmbiguousRef],
    name_index: dict[str, list[str]],
) -> tuple[list[Edge], list[AmbiguousRef]]:
    """Resolve or drop Java AmbiguousRefs using the symbol index.

    Applies Java-specific drop rules before the index lookup so common
    framework/stdlib method names never reach C4b.
    Returns (resolved_edges, remaining_refs_for_agent).
    """
    new_edges: list[Edge] = []
    remaining: list[AmbiguousRef] = []
    dropped = resolved = passed = 0

    for ref in refs:
        # Drop calls to universally-external method names before index lookup.
        if ref.kind == "call":
            call_name = _extract_call_name(ref.raw)
            if call_name in _JAVA_DROP_CALL_NAMES:
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
        reasoning = "symbol_index: unique match"

        if len(candidates) == 1:
            target = candidates[0]
        else:
            target = _same_package_heuristic(ref.source, candidates)
            if target:
                reasoning = "symbol_index: same-package heuristic"
            if target is None and ref.kind == "call":
                target = _call_receiver_heuristic(ref.raw, candidates)
                if target:
                    reasoning = "symbol_index: receiver-class heuristic"
            if target is None and ref.kind == "import":
                target = _import_fqn_heuristic(ref.raw, candidates)
                if target:
                    reasoning = "symbol_index: FQN path heuristic"

        if target is not None:
            edge_type = _KIND_TO_EDGE.get(ref.kind)
            if edge_type:
                new_edges.append(
                    Edge(
                        source=ref.source,
                        target=target,
                        type=edge_type,
                        confidence="INFERRED",
                        metadata={"reasoning": reasoning, "raw": ref.raw},
                    )
                )
                resolved += 1
            else:
                dropped += 1
        elif ref.kind == "import":
            # Java FQN imports are unambiguous by language spec. If neither
            # same-package nor FQN-path matched a candidate's file path, this
            # import targets an external package that happens to share a
            # simple name with project code — passing it to the agent would
            # produce a false-positive INFERRED edge.
            dropped += 1
        else:
            remaining.append(ref)
            passed += 1

    total = dropped + resolved + passed
    logger.debug(
        "java: %d total — dropped %d  resolved %d  passed %d",
        total, dropped, resolved, passed,
    )
    return new_edges, remaining


# ---------------------------------------------------------------------------
# Symbol name extraction (Java-specific)
# ---------------------------------------------------------------------------

def _extract_symbol_name(ref: AmbiguousRef) -> str:
    """Derive the simple lookup name from the raw ref text (Java-specific)."""
    raw = ref.raw.strip()

    if ref.kind == "import":
        return _parse_import_name(raw)

    if ref.kind in ("inherits", "decorator"):
        # Strip generic notation: "BaseEntity<T>" → "BaseEntity"
        return raw.split("<")[0].strip()

    if ref.kind == "call":
        return _extract_call_name(raw)

    return raw


def _parse_import_name(raw: str) -> str:
    """Extract the class name from a Java fully-qualified import.

    Examples:
      "import com.example.service.UserService;"  → "UserService"
      "import com.example.service.*"             → "" (wildcard, unresolvable)
      "import static com.example.Utils.helper;"  → "helper"
    """
    cleaned = raw.strip().removeprefix("import").replace(";", "").strip()
    # "static com.example.Utils.helper" → "com.example.Utils.helper"
    cleaned = cleaned.removeprefix("static").strip()

    if cleaned.endswith("*"):
        return ""

    return cleaned.rsplit(".", 1)[-1]


def _extract_call_name(raw: str) -> str:
    """Extract the method name from a Java call expression.

    Examples:
      "userService.save"      → "save"
      "this.processOrder"     → "processOrder"
      "save"                  → "save"
      "a.b.c.doSomething"     → "doSomething"
    """
    name_part = raw.split("(")[0].strip()
    return name_part.rsplit(".", 1)[-1].strip()


# ---------------------------------------------------------------------------
# Shared heuristics
# ---------------------------------------------------------------------------

def _call_receiver_heuristic(raw: str, candidates: list[str]) -> str | None:
    """Use the receiver variable name to narrow call candidates to one class.

    Spring naming convention: field 'userService' → class 'UserService' (or
    'UserServiceImpl').  Works for both direct and this-qualified field calls:
      "userService.save"       → receiver="userService" → class="UserService"
      "this.userService.save"  → strip "this" → same result
      "UserUtils.sanitize"     → uppercase receiver → static call exact match

    Returns None if the heuristic cannot narrow to exactly one candidate.
    """
    parts = raw.rsplit(".", 1)
    if len(parts) < 2:
        return None
    receiver_chain, method_name = parts[0], parts[1]

    # Strip "this" / "super" from the chain; take the last remaining segment.
    receiver_parts = [p for p in receiver_chain.split(".") if p not in ("this", "super", "")]
    if not receiver_parts:
        return None
    receiver = receiver_parts[-1]
    if not receiver:
        return None

    if receiver[0].isupper():
        # Static call — look for exact ::ReceiverClass.methodName match.
        needle = f"::{receiver}.{method_name}"
        matched = [c for c in candidates if needle in c]
    else:
        # Instance field call — capitalize → likely class name.
        likely = receiver[0].upper() + receiver[1:]
        matched = [
            c for c in candidates
            if f"::{likely}.{method_name}" in c or f"::{likely}Impl.{method_name}" in c
        ]

    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        # Still ambiguous — try same-package as a tie-breaker.
        return None
    return None


def _import_fqn_heuristic(raw: str, candidates: list[str]) -> str | None:
    """Match a Java FQN import against project file paths.

    Java package structure maps 1-to-1 to directory structure, so:
      "import com.example.service.UserService;"
      → fqn_path = "com/example/service/UserService.java"
      → file path of the candidate must end with that suffix

    For static imports (e.g. "import static com.example.Utils.helper;") the
    method name is the last component; we try the class path as a fallback.
    """
    cleaned = raw.strip().removeprefix("import").replace(";", "").strip()
    cleaned = cleaned.removeprefix("static").strip()
    if not cleaned or cleaned.endswith("*"):
        return None

    fqn_path = cleaned.replace(".", "/") + ".java"
    matched = [c for c in candidates if _file_of(c).endswith(fqn_path)]
    if len(matched) == 1:
        return matched[0]

    # Static import: last segment is the member name, not the class name.
    # Try stripping it and matching the class file instead.
    if "/" in fqn_path:
        class_path = fqn_path.rsplit("/", 1)[0] + ".java"
        matched = [c for c in candidates if _file_of(c).endswith(class_path)]
        if len(matched) == 1:
            return matched[0]

    return None


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
