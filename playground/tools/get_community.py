"""Fetch nodes belonging to a Leiden community cluster.

Returns god nodes (high-connectivity hubs) first, then regular members,
capped so the result stays within a useful token budget.
"""

from __future__ import annotations

from typing import Any


def run(
    community_id: int,
    graph_data: dict[str, Any],
    *,
    max_nodes: int = 20,
) -> dict[str, Any]:
    """Return a summary of a community cluster.

    Result dict:
        found: bool
        community_id: int
        total_members: int
        truncated: bool
        nodes: list of {id, name, type, file, line_start, is_god, is_orphan}
    """
    nodes: list[dict] = graph_data.get("nodes", [])

    members = [n for n in nodes if n.get("community") == community_id]
    if not members:
        return {"found": False, "community_id": community_id}

    gods = [n for n in members if n.get("is_god")]
    rest = [n for n in members if not n.get("is_god") and not n.get("is_orphan")]
    orphans = [n for n in members if n.get("is_orphan")]

    # god nodes first, then regular, then orphans
    ordered = (gods + rest + orphans)[:max_nodes]

    return {
        "found": True,
        "community_id": community_id,
        "total_members": len(members),
        "god_node_count": len(gods),
        "orphan_count": len(orphans),
        "truncated": len(members) > max_nodes,
        "nodes": [
            {
                "id": n.get("id"),
                "name": n.get("name"),
                "type": n.get("type"),
                "file": n.get("file"),
                "line_start": n.get("line_start"),
                "is_god": n.get("is_god", False),
                "is_orphan": n.get("is_orphan", False),
            }
            for n in ordered
        ],
    }
