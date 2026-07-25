"""C5a — Graph Builder.

Loads a persisted parse tree (C4a+C4b output) by `tree_id` and merges its
EXTRACTED + INFERRED edges into a single `networkx.MultiDiGraph` that C5b will
consume for Leiden community detection.

Edges that reference endpoints not present in `tree.nodes` (cross-repo
imports, module-level globals tree-sitter doesn't extract as nodes) get a
synthetic `external` node so the graph stays structurally complete and
doesn't lose those signals before clustering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import networkx as nx

from graph_engine.utils.db_utils import LoadedTree, load_tree

logger = logging.getLogger("meridian.graph_engine.networkx")

_VALID_EDGE_TYPES: frozenset[str] = frozenset(
    {
        "IMPORTS",
        "CALLS",
        "CONTAINS",
        "INHERITS",
        "DECORATES",
        "RELATES_TO",
        "DEPENDS_ON",
    }
)


@dataclass
class GraphBuildResult:
    graph: nx.MultiDiGraph
    tree_id: str
    graph_id: str | None
    last_commit_sha: str | None
    node_count: int
    edge_count: int
    external_node_count: int
    edges_dropped: int


def build_graph(tree_id: str) -> GraphBuildResult:
    """Build a NetworkX MultiDiGraph from the parse tree at `tree_id`."""
    loaded = load_tree(tree_id)
    return _build(loaded)


def _build(loaded: LoadedTree) -> GraphBuildResult:
    tree = loaded.tree_data
    raw_nodes = tree.get("nodes", []) or []
    raw_edges = tree.get("edges", []) or []

    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.graph["repo"] = tree.get("repo")
    g.graph["root"] = tree.get("root")
    g.graph["tree_id"] = loaded.tree_id
    g.graph["graph_id"] = loaded.graph_id
    g.graph["last_commit_sha"] = loaded.last_commit_sha

    for n in raw_nodes:
        g.add_node(
            n["id"],
            type=n.get("type"),
            name=n.get("name"),
            file=n.get("file"),
            line_start=n.get("line_start"),
            line_end=n.get("line_end"),
            language=n.get("language"),
            params=n.get("params", []),
            docstring=n.get("docstring"),
            return_type=n.get("return_type"),
        )

    edges_added = 0
    edges_dropped = 0
    external_nodes: set[str] = set()

    for e in raw_edges:
        etype = e.get("type")
        if etype not in _VALID_EDGE_TYPES:
            edges_dropped += 1
            logger.warning("graph_builder: dropping edge with unknown type=%s", etype)
            continue

        source = e["source"]
        target = e["target"]

        for endpoint in (source, target):
            if endpoint not in g:
                g.add_node(
                    endpoint,
                    type="external",
                    name=endpoint,
                    file=None,
                    line_start=None,
                    line_end=None,
                    language=None,
                    params=[],
                    docstring=None,
                    return_type=None,
                )
                external_nodes.add(endpoint)

        g.add_edge(
            source,
            target,
            type=etype,
            confidence=e.get("confidence", "EXTRACTED"),
            weight=float(e.get("weight", 1.0)),
            metadata=e.get("metadata", {}),
        )
        edges_added += 1

    result = GraphBuildResult(
        graph=g,
        tree_id=loaded.tree_id,
        graph_id=loaded.graph_id,
        last_commit_sha=loaded.last_commit_sha,
        node_count=g.number_of_nodes(),
        edge_count=edges_added,
        external_node_count=len(external_nodes),
        edges_dropped=edges_dropped,
    )

    logger.info(
        "graph_builder: tree_id=%s nodes=%d edges=%d external=%d dropped=%d",
        result.tree_id,
        result.node_count,
        result.edge_count,
        result.external_node_count,
        result.edges_dropped,
    )
    return result
