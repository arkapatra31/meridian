"""Unit tests for graph_engine.networkX_graph_builder._build.

Tests call the internal `_build(LoadedTree)` directly — no DB, no network.
`LoadedTree` is a plain dataclass, so we can construct it from raw dicts.
"""

from graph_engine.networkX_graph_builder.builder import _build
from graph_engine.utils.db_utils import LoadedTree


# ── helpers ───────────────────────────────────────────────────────────────────


def _loaded(
    nodes: list[dict] | None = None,
    edges: list[dict] | None = None,
    tree_id: str = "t1",
    graph_id: str = "g1",
    sha: str = "abc123",
) -> LoadedTree:
    return LoadedTree(
        tree_id=tree_id,
        graph_id=graph_id,
        last_commit_sha=sha,
        tree_data={
            "repo": "myrepo",
            "root": "/repo",
            "nodes": nodes or [],
            "edges": edges or [],
        },
    )


def _raw_node(
    node_id: str,
    ntype: str = "function",
    lang: str = "python",
) -> dict:
    return {
        "id": node_id,
        "type": ntype,
        "name": node_id.split("::")[-1],
        "file": node_id.split("::")[0],
        "line_start": 1,
        "line_end": 5,
        "language": lang,
        "params": [],
        "docstring": None,
        "return_type": None,
    }


def _raw_edge(
    source: str,
    target: str,
    etype: str = "CALLS",
    confidence: str = "EXTRACTED",
) -> dict:
    return {
        "source": source,
        "target": target,
        "type": etype,
        "confidence": confidence,
        "weight": 1.0,
        "metadata": {},
    }


# ─────────────────────────────────────────────────────────────────────────────


def test_empty_tree_produces_empty_graph():
    result = _build(_loaded())
    assert result.graph.number_of_nodes() == 0
    assert result.graph.number_of_edges() == 0
    assert result.node_count == 0
    assert result.edge_count == 0
    assert result.edges_dropped == 0
    assert result.external_node_count == 0


def test_nodes_added_with_correct_attributes():
    result = _build(_loaded(nodes=[_raw_node("a.py::Foo", ntype="class")]))
    g = result.graph
    assert "a.py::Foo" in g
    assert g.nodes["a.py::Foo"]["type"] == "class"
    assert g.nodes["a.py::Foo"]["language"] == "python"
    assert g.nodes["a.py::Foo"]["file"] == "a.py"


def test_valid_edges_added_to_graph():
    result = _build(_loaded(
        nodes=[_raw_node("a.py::foo"), _raw_node("b.py::bar")],
        edges=[_raw_edge("a.py::foo", "b.py::bar", "CALLS")],
    ))
    assert result.edge_count == 1
    assert result.edges_dropped == 0
    g = result.graph
    edge_types = [d["type"] for _, _, d in g.edges(data=True)]
    assert "CALLS" in edge_types


def test_invalid_edge_type_is_dropped():
    result = _build(_loaded(
        nodes=[_raw_node("a.py::foo"), _raw_node("b.py::bar")],
        edges=[_raw_edge("a.py::foo", "b.py::bar", "UNKNOWN_TYPE")],
    ))
    assert result.edge_count == 0
    assert result.edges_dropped == 1


def test_all_valid_edge_types_accepted():
    valid = ["IMPORTS", "CALLS", "CONTAINS", "INHERITS", "DECORATES", "RELATES_TO", "DEPENDS_ON"]
    nodes = [_raw_node(f"f{i}.py::fn") for i in range(len(valid) + 1)]
    edges = [
        _raw_edge(f"f{i}.py::fn", f"f{i+1}.py::fn", etype)
        for i, etype in enumerate(valid)
    ]
    result = _build(_loaded(nodes=nodes, edges=edges))
    assert result.edge_count == len(valid)
    assert result.edges_dropped == 0


def test_external_node_synthesized_for_unknown_endpoint():
    result = _build(_loaded(
        nodes=[_raw_node("a.py::foo")],
        edges=[_raw_edge("a.py::foo", "external_lib::SomeClass", "IMPORTS")],
    ))
    g = result.graph
    assert "external_lib::SomeClass" in g
    assert g.nodes["external_lib::SomeClass"]["type"] == "external"
    assert g.nodes["external_lib::SomeClass"]["file"] is None
    assert result.external_node_count == 1


def test_node_count_includes_external_nodes():
    result = _build(_loaded(
        nodes=[_raw_node("a.py::foo")],
        edges=[_raw_edge("a.py::foo", "stdlib::open", "CALLS")],
    ))
    # 1 parsed node + 1 external node synthesised for stdlib::open
    assert result.node_count == 2
    assert result.external_node_count == 1


def test_graph_metadata_propagated_from_loaded_tree():
    result = _build(_loaded(tree_id="tree-42", graph_id="graph-99", sha="deadbeef"))
    g = result.graph
    assert g.graph["tree_id"] == "tree-42"
    assert g.graph["graph_id"] == "graph-99"
    assert g.graph["last_commit_sha"] == "deadbeef"
    assert result.tree_id == "tree-42"
    assert result.graph_id == "graph-99"
    assert result.last_commit_sha == "deadbeef"


def test_inferred_confidence_preserved_on_edge():
    result = _build(_loaded(
        nodes=[_raw_node("a.py::foo"), _raw_node("b.py::bar")],
        edges=[_raw_edge("a.py::foo", "b.py::bar", "CALLS", confidence="INFERRED")],
    ))
    g = result.graph
    edges = list(g.edges(data=True))
    assert edges[0][2]["confidence"] == "INFERRED"
