"""Unit tests for hybrid_parsing.workload_reducer.

All tests are pure Python — no DB, no network, no LLM calls.

Reducer semantics:
  - No candidate for symbol name → ref is DROPPED (not passed to agent)
  - Exactly one candidate           → RESOLVED to an edge
  - Multiple candidates, same-pkg match → RESOLVED via heuristic
  - Multiple candidates, no pkg match   → passed through to agent (remaining)
"""

from hybrid_parsing.codebase_parser.models import AmbiguousRef, Edge, Node, ParseResult
from hybrid_parsing.workload_reducer.reducer import _build_name_index, reduce_workload
from hybrid_parsing.workload_reducer.reducer_python import _parse_import_name, reduce_python_refs


# ── helpers ───────────────────────────────────────────────────────────────────


def _node(node_id: str, name: str | None = None) -> Node:
    return Node(
        id=node_id, type="function",
        name=name or node_id.split("::")[-1],
        file=node_id.split("::")[0],
        line_start=1, line_end=5, language="python",
    )


def _ref(
    source: str,
    raw: str,
    kind: str = "import",
    file: str = "src/a.py",
) -> AmbiguousRef:
    return AmbiguousRef(source=source, raw=raw, kind=kind, file=file, line=1)


def _pr(nodes=(), ambiguous=(), edges=()) -> ParseResult:
    return ParseResult(
        repo="repo", root="/repo",
        nodes=list(nodes), edges=list(edges), ambiguous=list(ambiguous),
    )


# ── early-return guard ────────────────────────────────────────────────────────


def test_empty_ambiguous_returns_same_object():
    pr = _pr(nodes=[_node("a.py::Foo")])
    result = reduce_workload(pr)
    assert result is pr
    assert result.ambiguous == []


# ── unique resolution → edge ──────────────────────────────────────────────────


def test_unique_import_produces_imports_edge():
    node = _node("services/user.py::UserService", "UserService")
    ref = _ref(
        "src/main.py::run",
        "from services.user import UserService",
        kind="import",
        file="src/main.py",
    )
    pr = _pr(nodes=[node], ambiguous=[ref])
    result = reduce_workload(pr)
    assert result.ambiguous == []
    assert any(
        e.type == "IMPORTS" and e.target == "services/user.py::UserService"
        for e in result.edges
    )


def test_unique_call_produces_calls_edge():
    node = _node("utils/helper.py::process", "process")
    ref = _ref("src/main.py::run", "obj.process(x)", kind="call", file="src/main.py")
    pr = _pr(nodes=[node], ambiguous=[ref])
    result = reduce_workload(pr)
    assert result.ambiguous == []
    assert any(e.type == "CALLS" for e in result.edges)


def test_unique_inherits_produces_inherits_edge():
    node = _node("base/model.py::Base", "Base")
    ref = _ref("app/user.py::User", "Base", kind="inherits", file="app/user.py")
    pr = _pr(nodes=[node], ambiguous=[ref])
    result = reduce_workload(pr)
    assert any(e.type == "INHERITS" for e in result.edges)


def test_unique_decorator_produces_decorates_edge():
    node = _node("decorators.py::cached", "cached")
    ref = _ref("app/views.py::view", "cached", kind="decorator", file="app/views.py")
    pr = _pr(nodes=[node], ambiguous=[ref])
    result = reduce_workload(pr)
    assert any(e.type == "DECORATES" for e in result.edges)


def test_resolved_edge_has_inferred_confidence():
    node = _node("utils.py::helper", "helper")
    ref = _ref("src/a.py::fn", "helper()", kind="call", file="src/a.py")
    pr = _pr(nodes=[node], ambiguous=[ref])
    result = reduce_workload(pr)
    assert all(e.confidence == "INFERRED" for e in result.edges)


# ── no candidate → dropped ────────────────────────────────────────────────────


def test_unknown_symbol_dropped_not_remaining():
    ref = _ref("src/a.py::foo", "from unknown.module import Ghost", kind="import")
    pr = _pr(ambiguous=[ref])
    result = reduce_workload(pr)
    assert result.ambiguous == []
    assert result.edges == []


# ── multiple candidates → passed to agent ────────────────────────────────────


def test_ambiguous_candidates_passed_through():
    nodes = [
        _node("a/service.py::Helper", "Helper"),
        _node("b/utils.py::Helper", "Helper"),
    ]
    # Source is in src/ which is a different package from both candidates
    ref = _ref("src/main.py::run", "from x import Helper", kind="import", file="src/main.py")
    pr = _pr(nodes=nodes, ambiguous=[ref])
    result = reduce_workload(pr)
    assert len(result.ambiguous) == 1


# ── same-package heuristic ────────────────────────────────────────────────────


def test_same_package_heuristic_resolves_sibling():
    nodes = [
        _node("src/utils.py::helper", "helper"),    # same package as caller
        _node("other/utils.py::helper", "helper"),  # different package
    ]
    ref = _ref("src/main.py::run", "from .utils import helper", kind="import", file="src/main.py")
    pr = _pr(nodes=nodes, ambiguous=[ref])
    result = reduce_workload(pr)
    assert len(result.edges) == 1
    assert result.edges[0].target == "src/utils.py::helper"


# ── _parse_import_name unit tests ─────────────────────────────────────────────


def test_parse_import_single_name():
    assert _parse_import_name("from services import UserService") == "UserService"


def test_parse_import_with_alias():
    assert _parse_import_name("from services import UserService as US") == "UserService"


def test_parse_import_multi_name_returns_empty():
    assert _parse_import_name("from services import A, B") == ""


def test_parse_import_dotted_module():
    assert _parse_import_name("import services.user") == "user"


def test_parse_import_star_returns_empty():
    assert _parse_import_name("from services import *") == ""


def test_parse_import_relative():
    assert _parse_import_name("from .utils import helper") == "helper"


# ── name index helper ─────────────────────────────────────────────────────────


def test_build_name_index_groups_by_name():
    nodes = [
        _node("a.py::Foo", "Foo"),
        _node("b.py::Foo", "Foo"),
        _node("c.py::Bar", "Bar"),
    ]
    idx = _build_name_index(_pr(nodes=nodes))
    assert sorted(idx["Foo"]) == sorted(["a.py::Foo", "b.py::Foo"])
    assert idx["Bar"] == ["c.py::Bar"]
