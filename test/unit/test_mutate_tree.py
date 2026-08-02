"""Unit tests for hybrid_parsing.tree_indexer.mutate_tree.

All tests are pure Python — no DB, no network.

Key semantics of mutate_tree:
  removed_ids  = nodes whose file is in stale_files
  returning_ids = node ids present in delta.nodes
  truly_removed = removed_ids - returning_ids

  Nodes:     all stale nodes dropped; delta nodes appended.
  Edges:     dropped if source in removed_ids OR target in truly_removed.
             (edges TO a stale node are kept if that node re-appears in delta)
  Ambiguous: dropped if ref.file in stale_files.
  Metadata:  languages summed; files_parsed/skipped = max(existing, delta).
"""

from hybrid_parsing.codebase_parser.models import AmbiguousRef, Edge, Node, ParseResult
from hybrid_parsing.tree_indexer.indexer import mutate_tree


# ── helpers ───────────────────────────────────────────────────────────────────


def _node(node_id: str, file: str | None = None) -> Node:
    f = file or node_id.split("::")[0]
    return Node(
        id=node_id, type="function", name=node_id.split("::")[-1],
        file=f, line_start=1, line_end=10, language="python",
    )


def _edge(source: str, target: str, edge_type: str = "CALLS") -> Edge:
    return Edge(source=source, target=target, type=edge_type)


def _aref(source: str, file: str) -> AmbiguousRef:
    return AmbiguousRef(source=source, raw="from x import y", kind="import", file=file, line=1)


def _pr(**kwargs) -> ParseResult:
    return ParseResult(repo="repo", root="/repo", **kwargs)


# ── node mutation ─────────────────────────────────────────────────────────────


def test_stale_nodes_removed():
    existing = _pr(nodes=[_node("a.py::foo", "a.py"), _node("b.py::bar", "b.py")])
    result = mutate_tree(existing, stale_files={"a.py"}, delta=_pr())
    ids = [n.id for n in result.nodes]
    assert "a.py::foo" not in ids
    assert "b.py::bar" in ids


def test_delta_nodes_spliced_in():
    existing = _pr(nodes=[_node("a.py::foo", "a.py")])
    delta = _pr(nodes=[_node("a.py::new_fn", "a.py")])
    result = mutate_tree(existing, stale_files={"a.py"}, delta=delta)
    assert any(n.id == "a.py::new_fn" for n in result.nodes)


def test_returning_node_appears_exactly_once():
    """Stale node that re-appears in delta must not be duplicated."""
    existing = _pr(nodes=[_node("a.py::foo", "a.py")])
    delta = _pr(nodes=[_node("a.py::foo", "a.py")])
    result = mutate_tree(existing, stale_files={"a.py"}, delta=delta)
    assert [n.id for n in result.nodes].count("a.py::foo") == 1


def test_non_stale_nodes_untouched():
    existing = _pr(nodes=[_node("a.py::foo", "a.py"), _node("b.py::bar", "b.py")])
    result = mutate_tree(existing, stale_files=set(), delta=_pr())
    assert len(result.nodes) == 2


# ── edge mutation ─────────────────────────────────────────────────────────────


def test_edge_dropped_when_source_is_stale():
    existing = _pr(
        nodes=[_node("a.py::foo", "a.py"), _node("b.py::bar", "b.py")],
        edges=[_edge("a.py::foo", "b.py::bar")],
    )
    result = mutate_tree(existing, stale_files={"a.py"}, delta=_pr())
    assert result.edges == []


def test_edge_dropped_when_target_truly_removed():
    """Edge B→A is dropped when A is stale and does not return in delta."""
    existing = _pr(
        nodes=[_node("a.py::foo", "a.py"), _node("b.py::bar", "b.py")],
        edges=[_edge("b.py::bar", "a.py::foo")],
    )
    result = mutate_tree(existing, stale_files={"a.py"}, delta=_pr())
    assert result.edges == []


def test_edge_kept_when_target_returns_in_delta():
    """Edge B→A is kept when A is stale but re-appears in the delta."""
    existing = _pr(
        nodes=[_node("a.py::foo", "a.py"), _node("b.py::bar", "b.py")],
        edges=[_edge("b.py::bar", "a.py::foo")],
    )
    delta = _pr(nodes=[_node("a.py::foo", "a.py")])
    result = mutate_tree(existing, stale_files={"a.py"}, delta=delta)
    assert any(e.source == "b.py::bar" and e.target == "a.py::foo" for e in result.edges)


def test_edge_between_non_stale_nodes_kept():
    existing = _pr(
        nodes=[_node("a.py::foo", "a.py"), _node("b.py::bar", "b.py"), _node("c.py::baz", "c.py")],
        edges=[_edge("b.py::bar", "c.py::baz")],
    )
    result = mutate_tree(existing, stale_files={"a.py"}, delta=_pr())
    assert any(e.source == "b.py::bar" and e.target == "c.py::baz" for e in result.edges)


# ── ambiguous ref mutation ────────────────────────────────────────────────────


def test_ambiguous_refs_for_stale_file_removed():
    existing = _pr(ambiguous=[_aref("a.py::foo", "a.py"), _aref("b.py::bar", "b.py")])
    result = mutate_tree(existing, stale_files={"a.py"}, delta=_pr())
    assert all(a.file != "a.py" for a in result.ambiguous)
    assert any(a.file == "b.py" for a in result.ambiguous)


# ── metadata merging ──────────────────────────────────────────────────────────


def test_language_counts_summed():
    existing = _pr(languages={"python": 3, "java": 1})
    delta = _pr(languages={"python": 2, "typescript": 1})
    result = mutate_tree(existing, stale_files=set(), delta=delta)
    assert result.languages == {"python": 5, "java": 1, "typescript": 1}


def test_files_parsed_and_skipped_use_max():
    existing = _pr(files_parsed=10, files_skipped=2)
    delta = _pr(files_parsed=15, files_skipped=1)
    result = mutate_tree(existing, stale_files=set(), delta=delta)
    assert result.files_parsed == 15
    assert result.files_skipped == 2


def test_errors_from_delta_appended():
    existing = _pr(errors=["err1"])
    delta = _pr(errors=["err2"])
    result = mutate_tree(existing, stale_files=set(), delta=delta)
    assert "err1" in result.errors
    assert "err2" in result.errors


def test_empty_stale_empty_delta_is_noop():
    node = _node("a.py::foo", "a.py")
    edge = _edge("a.py::foo", "b.py::bar")
    existing = _pr(nodes=[node], edges=[edge])
    result = mutate_tree(existing, stale_files=set(), delta=_pr())
    assert len(result.nodes) == 1
    assert len(result.edges) == 1
