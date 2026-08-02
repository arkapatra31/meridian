"""C5b — Leiden community detection.

Loads the C5a-built graph from `graphs.graph_data` by `graph_id`, runs Leiden
on its undirected weighted projection, writes a `community` integer onto
each node, marks god / orphan nodes, and UPDATEs the same row in place
flipping `status` to `ready` (per CLAUDE.md C5b contract).

Leiden runs on undirected, simple, weighted graphs. The C5a builder produces
a `MultiDiGraph` (directed, multi-edge) so we collapse parallel and
direction-flipped edges into one weighted edge, summing weights — a strong
caller↔callee tie stays visible to the algorithm as a strong topology.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import networkx as nx

from graph_engine.utils.db_utils import load_graph, update_graph_with_clusters  # load_graph kept for backward compat

logger = logging.getLogger("meridian.graph_engine.leiden")

_DEFAULT_RESOLUTION = 1.0
_GOD_NODE_COMMUNITY_THRESHOLD = 2


@dataclass
class ClusterResult:
    graph_id: str
    graph: nx.MultiDiGraph
    community_count: int
    god_node_count: int
    orphan_node_count: int


def cluster_graph(
    graph_id: str,
    *,
    graph: nx.MultiDiGraph | None = None,
    node_count: int | None = None,
    edge_count: int | None = None,
    last_commit_sha: str | None = None,
    repo_clone_id: str | None = None,
    resolution: float = _DEFAULT_RESOLUTION,
    random_seed: int | None = None,
) -> ClusterResult:
    """Run Leiden on the graph at `graph_id` and persist the partition.

    Pass `graph` to skip the DB reload — the orchestrator already has the
    `MultiDiGraph` in memory from C5a and can hand it straight through.
    When `graph` is None the row is loaded from DB (backward-compatible path).
    `node_count`, `edge_count`, `last_commit_sha`, `repo_clone_id` are
    forwarded to `update_graph_with_clusters` so the final persist writes
    everything in one shot (H4 — no intermediate persist_graph round-trip).
    """
    if graph is None:
        loaded = load_graph(graph_id)
        g = loaded.graph
    else:
        g = graph

    partition = _run_leiden(g, resolution=resolution, random_seed=random_seed)
    nx.set_node_attributes(g, partition, "community")

    god_nodes = _mark_god_nodes(g, partition)
    orphan_nodes = _mark_orphan_nodes(g)

    community_count = len(set(partition.values()))

    update_graph_with_clusters(
        graph_id,
        graph=g,
        community_count=community_count,
        node_count=node_count,
        edge_count=edge_count,
        last_commit_sha=last_commit_sha,
        repo_clone_id=repo_clone_id,
    )

    logger.info(
        "leiden: graph_id=%s communities=%d god=%d orphan=%d",
        graph_id,
        community_count,
        len(god_nodes),
        len(orphan_nodes),
    )

    return ClusterResult(
        graph_id=graph_id,
        graph=g,
        community_count=community_count,
        god_node_count=len(god_nodes),
        orphan_node_count=len(orphan_nodes),
    )


def _run_leiden(
    g: nx.MultiDiGraph,
    *,
    resolution: float,
    random_seed: int | None,
) -> dict[str, int]:
    """Project to an undirected weighted simple graph and partition."""
    simple = _to_undirected_weighted(g)

    if simple.number_of_edges() == 0:
        # No edges → every node is its own community. Skip the algo so
        # graspologic doesn't complain about empty inputs.
        return {node: idx for idx, node in enumerate(simple.nodes())}

    # Lazy import: graspologic pulls in umap/pynndescent/numba and adds
    # ~4s to module load. We only pay it on the first build, never on
    # FastAPI cold start.
    from graspologic.partition import leiden

    return leiden(
        simple,
        resolution=resolution,
        is_weighted=True,
        weight_attribute="weight",
        random_seed=random_seed,
    )


def _to_undirected_weighted(g: nx.MultiDiGraph) -> nx.Graph:
    """Collapse parallel + reverse edges into a single weighted edge."""
    h: nx.Graph = nx.Graph()
    h.add_nodes_from(g.nodes())
    for u, v, data in g.edges(data=True):
        if u == v:
            continue
        w = float(data.get("weight", 1.0))
        if h.has_edge(u, v):
            h[u][v]["weight"] += w
        else:
            h.add_edge(u, v, weight=w)
    return h


def _mark_god_nodes(
    g: nx.MultiDiGraph, partition: dict[str, int]
) -> list[str]:
    """Tag nodes that bridge multiple communities (`is_god=True`).

    A node is a "god node" if its neighbours span 2+ communities other than
    its own — typical utility / registry / dispatcher hubs Leiden cannot
    cleanly place.
    """
    god: list[str] = []
    for node in g.nodes():
        own = partition.get(node)
        neighbour_communities = {
            partition[nb]
            for nb in set(g.successors(node)) | set(g.predecessors(node))
            if nb in partition
        }
        neighbour_communities.discard(own)
        is_god = len(neighbour_communities) >= _GOD_NODE_COMMUNITY_THRESHOLD
        g.nodes[node]["is_god"] = is_god
        if is_god:
            god.append(node)
    return god


def _mark_orphan_nodes(g: nx.MultiDiGraph) -> list[str]:
    """Tag isolates (`is_orphan=True`) — dead-code candidates surfaced to QnA."""
    orphans: list[str] = []
    for node in g.nodes():
        is_orphan = (g.in_degree(node) + g.out_degree(node)) == 0
        g.nodes[node]["is_orphan"] = is_orphan
        if is_orphan:
            orphans.append(node)
    return orphans
