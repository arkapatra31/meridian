"""Graph query tools for the QnA agent (C6).

Each tool module exposes a `run(...)` function with focused logic:
  - search_nodes   — keyword search, returns top-K seeds with neighbours
  - get_neighbours — full neighbour list for a known node ID
  - get_community  — all members of a Leiden community cluster

`build_context(query, graph_data)` composes the three tools into a single
readable text block that the session injects as context per user turn.
The output is formatted prose/bullets (not raw JSON) so the model gets
signal, not noise.
"""

from __future__ import annotations

from typing import Any

from . import get_community, get_neighbours, search_nodes


def build_context(
    query: str,
    graph_data: dict[str, Any],
    *,
    top_k: int = 6,
) -> str:
    """Run all retrieval tools and format their results as readable text.

    Pipeline:
      1. search_nodes  — find top-K nodes matching the query keywords
      2. get_neighbours — enrich each seed with its full neighbour list
      3. get_community  — add community context for each unique community seen

    Returns a text block ready for injection into the model prompt.
    The output is deliberately concise — typically 800–1 500 tokens.
    """
    seeds = search_nodes.run(query, graph_data, top_k=top_k)

    if not seeds:
        # No keyword hits — fall back to god nodes as structural anchors
        god_nodes = [n for n in graph_data.get("nodes", []) if n.get("is_god")][:top_k]
        seeds = [
            {
                "id": n.get("id"),
                "name": n.get("name"),
                "type": n.get("type"),
                "file": n.get("file"),
                "line_start": n.get("line_start"),
                "line_end": n.get("line_end"),
                "community": n.get("community"),
                "is_god": True,
                "is_orphan": False,
                "neighbours": [],
            }
            for n in god_nodes
        ]

    # Enrich seeds: fetch full neighbour lists
    enriched = []
    for seed in seeds:
        nb_result = get_neighbours.run(seed["id"], graph_data, max_neighbours=20)
        if nb_result.get("found"):
            enriched.append((seed, nb_result))
        else:
            enriched.append((seed, None))

    # Collect unique communities from seeds
    community_ids: list[int] = []
    seen_cids: set[int] = set()
    for seed, _ in enriched:
        cid = seed.get("community")
        if cid is not None and cid not in seen_cids:
            seen_cids.add(cid)
            community_ids.append(cid)

    community_summaries: dict[int, dict] = {}
    for cid in community_ids[:4]:  # cap to 4 communities max
        result = get_community.run(cid, graph_data, max_nodes=12)
        if result.get("found"):
            community_summaries[cid] = result

    return _format(query, enriched, community_summaries)


def _format(
    query: str,
    enriched: list[tuple[dict, dict | None]],
    community_summaries: dict[int, dict],
) -> str:
    lines: list[str] = [f"Graph context for: {query!r}", ""]

    # ── Matched nodes ────────────────────────────────────────────────────────
    lines.append("### Matched nodes")
    for seed, nb in enriched:
        tag = " [hub]" if seed.get("is_god") else (" [orphan]" if seed.get("is_orphan") else "")
        loc = seed.get("file") or ""
        if seed.get("line_start"):
            loc += f":{seed['line_start']}"
            if seed.get("line_end"):
                loc += f"–{seed['line_end']}"
        cid = seed.get("community")
        community_tag = f" | community {cid}" if cid is not None else ""
        lines.append(
            f"\n**{seed.get('type', 'node')} `{seed.get('name') or seed.get('id')}`**"
            f"{tag}{community_tag}"
        )
        if loc:
            lines.append(f"  File: {loc}")

        if nb and nb.get("found"):
            inbound = nb.get("inbound", [])
            outbound = nb.get("outbound", [])

            if outbound:
                out_labels = [
                    f"`{n.get('name') or n.get('id')}` ({n.get('edge_type', '→')})"
                    for n in outbound[:8]
                ]
                lines.append(f"  Calls/uses: {', '.join(out_labels)}")

            if inbound:
                in_labels = [
                    f"`{n.get('name') or n.get('id')}` ({n.get('edge_type', '←')})"
                    for n in inbound[:8]
                ]
                lines.append(f"  Called/used by: {', '.join(in_labels)}")

    # ── Community summaries ──────────────────────────────────────────────────
    if community_summaries:
        lines.append("\n### Community clusters")
        for cid, cs in community_summaries.items():
            total = cs.get("total_members", 0)
            gods = cs.get("god_node_count", 0)
            trunc = " (truncated)" if cs.get("truncated") else ""
            lines.append(f"\n**Community {cid}** — {total} members, {gods} hub nodes{trunc}")
            member_labels = [
                f"`{n.get('name') or n.get('id')}`{'*' if n.get('is_god') else ''}"
                for n in cs.get("nodes", [])[:10]
            ]
            lines.append(f"  Members: {', '.join(member_labels)}")

    return "\n".join(lines)
