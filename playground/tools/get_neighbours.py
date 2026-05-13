"""Fetch all direct neighbours of a known node.

Used as a second-pass enrichment after search_nodes identifies seeds:
given a node ID, returns every inbound and outbound edge with the
neighbour's metadata.
"""

from __future__ import annotations

from typing import Any


def run(
    node_id: str,
    graph_data: dict[str, Any],
    *,
    max_neighbours: int = 25,
    edge_type: str | None = None,
) -> dict[str, Any]:
    """Return the node metadata plus all its direct neighbours.

    Result dict:
        found: bool
        node: {id, name, type, file, line_start, line_end, community, is_god}
        inbound:  list of neighbour dicts (things that depend on / call this node)
        outbound: list of neighbour dicts (things this node calls / depends on)
    """
    nodes: list[dict] = graph_data.get("nodes", [])
    edges: list[dict] = graph_data.get("edges", [])
    by_id: dict[str, dict] = {n["id"]: n for n in nodes if "id" in n}

    node = by_id.get(node_id)
    if node is None:
        # Fuzzy fallback: match on name or partial id
        q = node_id.lower()
        candidates = [
            n for n in nodes
            if q in str(n.get("id", "")).lower() or q in str(n.get("name", "")).lower()
        ]
        if not candidates:
            return {"found": False, "node_id": node_id}
        node = candidates[0]
        node_id = node["id"]

    def _nbr(other_id: str, et: str, direction: str) -> dict:
        nb = by_id.get(other_id, {})
        return {
            "id": other_id,
            "name": nb.get("name", other_id),
            "type": nb.get("type"),
            "file": nb.get("file"),
            "edge_type": et,
        }

    inbound, outbound = [], []
    for e in edges:
        s, t, et = e.get("source"), e.get("target"), e.get("type", "")
        if edge_type and et != edge_type:
            continue
        if t == node_id:
            inbound.append(_nbr(s, et, "in"))
        elif s == node_id:
            outbound.append(_nbr(t, et, "out"))

    # Cap per direction so the bundle stays bounded
    half = max_neighbours // 2
    return {
        "found": True,
        "node": {
            "id": node.get("id"),
            "name": node.get("name"),
            "type": node.get("type"),
            "file": node.get("file"),
            "line_start": node.get("line_start"),
            "line_end": node.get("line_end"),
            "community": node.get("community"),
            "is_god": node.get("is_god", False),
        },
        "inbound": inbound[:half],
        "outbound": outbound[:half],
    }
