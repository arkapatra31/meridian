"""Generate context/skill files for AI coding tools from a Meridian knowledge graph.

Supported tools
---------------
claude_code  → .claude/skills/<slug>/SKILL.md        (skill directory, frontmatter)
cursor       → .cursor/rules/<slug>-context.mdc       (MDC frontmatter + markdown)
copilot      → .github/copilot-instructions.md        (plain markdown, always-on)
windsurf     → .windsurf/rules/meridian-<slug>.md     (trigger frontmatter, always-on)

Design goal: maximise the information the coding agent can extract WITHOUT opening
source files.  Every hub node now carries its full signature and docstring first
line so the agent can reason about call chains and interfaces from the skill alone.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TOOL_CLAUDE_CODE = "claude_code"
TOOL_CURSOR      = "cursor"
TOOL_COPILOT     = "copilot"
TOOL_WINDSURF    = "windsurf"

SUPPORTED_TOOLS: frozenset[str] = frozenset(
    {TOOL_CLAUDE_CODE, TOOL_CURSOR, TOOL_COPILOT, TOOL_WINDSURF}
)


# ── Public API ─────────────────────────────────────────────────────────────────


def build_graph_anchor(graph_data: dict[str, Any]) -> str:
    """Return a compact hub-nodes + cluster map for the QnA system prompt.

    This is the static portion of graph context — injected once at session
    start and cached across all turns, so it is never re-written to the
    prompt cache on subsequent turns.
    """
    nodes: list[dict] = graph_data.get("nodes", [])
    edges: list[dict] = graph_data.get("edges", [])
    stats = _extract_stats(nodes, edges)
    ctx: dict[str, Any] = dict(nodes=nodes, edges=edges, **stats)
    return "\n".join(_build_claude_code_lines(ctx))


def generate_skill_file(
    graph_data: dict[str, Any],
    *,
    repo_url: str,
    branch: str,
    graph_id: str,
    last_commit_sha: str | None = None,
    tool: str = TOOL_CLAUDE_CODE,
) -> str:
    """Return the full file content for the requested tool."""
    nodes: list[dict] = graph_data.get("nodes", [])
    edges: list[dict] = graph_data.get("edges", [])

    stats     = _extract_stats(nodes, edges)
    repo_slug = _repo_slug(repo_url)
    sha_short = last_commit_sha[:8] if last_commit_sha else "unknown"

    ctx: dict[str, Any] = dict(
        nodes=nodes,
        edges=edges,
        repo_url=repo_url,
        branch=branch,
        graph_id=graph_id,
        repo_slug=repo_slug,
        sha_short=sha_short,
        **stats,
    )

    if tool == TOOL_CURSOR:
        return _generate_cursor(ctx)
    if tool == TOOL_COPILOT:
        return _generate_copilot(ctx)
    if tool == TOOL_WINDSURF:
        return _generate_windsurf(ctx)
    return _generate_claude_code(ctx)


def skill_slug() -> str:
    """Return the skill directory name for a Claude Code skill."""
    return "meridian"


def skill_filename(repo_url: str, tool: str = TOOL_CLAUDE_CODE) -> str:
    """Return the suggested download filename for the generated file."""
    slug = _repo_slug(repo_url)
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", slug)
    if tool == TOOL_CLAUDE_CODE:
        return "SKILL.md"
    if tool == TOOL_CURSOR:
        return f"{safe}-context.mdc"
    if tool == TOOL_COPILOT:
        return "copilot-instructions.md"
    if tool == TOOL_WINDSURF:
        return f"meridian-{safe}.md"
    return f"meridian-{safe}.md"


def skill_placement_path(repo_url: str, tool: str = TOOL_CLAUDE_CODE) -> str:
    """Return the path (relative to repo root) where the file should be placed."""
    fname = skill_filename(repo_url, tool)
    if tool == TOOL_CLAUDE_CODE:
        return f".claude/skills/{skill_slug()}/{fname}"
    if tool == TOOL_CURSOR:
        return f".cursor/rules/{fname}"
    if tool == TOOL_COPILOT:
        return f".github/{fname}"
    if tool == TOOL_WINDSURF:
        return f".windsurf/rules/{fname}"
    return fname


# ── Format generators ──────────────────────────────────────────────────────────


def _generate_claude_code(ctx: dict) -> str:
    repo_slug = ctx["repo_slug"]
    nodes       = ctx["nodes"]
    edges       = ctx["edges"]
    communities = ctx["communities"]
    lines: list[str] = []

    lines += [
        "---",
        f"description: Structural graph for {repo_slug} — locate nodes, trace call chains, map clusters without reading source files.",
        f"when_to_use: Before any question about code structure, dependencies, ownership, or call chains in {repo_slug}.",
        "---",
        "",
        f"# {repo_slug} · {ctx['branch']}@{ctx['sha_short']} · {len(nodes):,}n {len(edges):,}e {len(communities)}c",
        "",
    ]

    lines += _build_claude_code_lines(ctx)

    lines += [
        "",
        "---",
        "Answer from this graph first — infer domain concepts from node names, signatures, call chains, and cluster groupings. If the graph lacks sufficient detail, read source files surgically: use the hub file:line references and File Index to jump directly to the relevant location. Do not grep broadly or explore speculatively; the graph already tells you which files and lines are relevant.",
        "Cite: `name (file:line)`. Lookup → Hubs first, then Clusters, then File Index.",
        f"Graph: `{ctx['graph_id']}`",
    ]

    return "\n".join(lines)


def _generate_cursor(ctx: dict) -> str:
    repo_slug    = ctx["repo_slug"]
    lang_counter = ctx["lang_counter"]
    lines: list[str] = []

    globs = _lang_globs(lang_counter)
    lines += ["---", f"description: Meridian graph context for {repo_slug} — hub nodes, clusters, call chains"]
    if globs:
        lines.append(f"globs: {','.join(globs[:6])}")
    lines += [
        "alwaysApply: false",
        "---",
        "",
        f"# Meridian graph context — {repo_slug}",
        "",
        f"Use this structural context when answering questions about the **{repo_slug}** codebase.",
        "Reference hub nodes as architectural anchors and respect cluster boundaries.",
        "Hub node entries include full signatures and docstrings — use them to reason about",
        "interfaces and call chains without opening source files.",
        "",
        "---",
        "",
    ]

    lines += _build_common_lines(ctx)

    lines += [
        "---",
        "",
        "**Hub nodes** are the highest-connectivity anchors — start there when tracing unfamiliar paths.",
        "**Same-cluster nodes** are functionally cohesive — changes to one often affect neighbours.",
        "",
        f"*Graph ID: `{ctx['graph_id']}` · Generated by Meridian*",
    ]

    return "\n".join(lines)


def _generate_copilot(ctx: dict) -> str:
    repo_slug = ctx["repo_slug"]
    lines: list[str] = []

    lines += [
        f"# Codebase context: {repo_slug}",
        "",
        f"Generated by Meridian from the `{ctx['branch']}` branch (commit `{ctx['sha_short']}`).",
        "Use this to answer questions about code structure, dependencies, and architecture.",
        "Hub node entries include full signatures and docstrings — use them to reason about",
        "interfaces and call chains without opening source files.",
        "",
    ]

    lines += _build_common_lines(ctx)

    lines += [
        "---",
        f"*Generated by Meridian · Graph `{ctx['graph_id']}`*",
    ]

    return "\n".join(lines)


def _generate_windsurf(ctx: dict) -> str:
    repo_slug = ctx["repo_slug"]
    lines: list[str] = []

    lines += [
        "---",
        "trigger: always_on",
        "---",
        "",
        f"# Meridian — {repo_slug}",
        "",
        f"Knowledge graph context for the **{repo_slug}** codebase (`{ctx['branch']}` branch, commit `{ctx['sha_short']}`).",
        "Reference the hub nodes and community clusters below when reasoning about code structure.",
        "Hub node entries include full signatures and docstrings — use them to reason about",
        "interfaces and call chains without opening source files.",
        "",
    ]

    lines += _build_common_lines(ctx)

    lines += [
        "---",
        f"*Generated by Meridian · Graph `{ctx['graph_id']}`*",
    ]

    return "\n".join(lines)


# ── Shared body ────────────────────────────────────────────────────────────────


def _build_claude_code_lines(ctx: dict) -> list[str]:
    """Ultra-compact body optimised for LLM consumption.

    Hub line:   name(params) -> ret type Ccluster file:line →A(→A1,A2),B ←caller1
    Doc line:   (indented 2 spaces) first docstring line — only when present
    Cluster:    Cid(count★ purpose) hub1,hub2,member3,member4
    File index: file → Cid[★]: node1★,node2 [+N]
    """
    god_nodes        = ctx["god_nodes"]
    orphan_count     = ctx["orphan_count"]
    communities      = ctx["communities"]
    adj              = ctx["adj"]
    edge_map         = ctx["edge_map"]
    reverse_edge_map = ctx["reverse_edge_map"]
    node_by_id       = ctx["node_by_id"]
    nodes            = ctx["nodes"]

    lines: list[str] = []

    # ── Hub nodes — two lines each (line 2 only when docstring exists) ─────────
    if god_nodes:
        lines.append("## Hubs")
        god_sorted = sorted(god_nodes, key=lambda n: len(adj.get(n.get("id", ""), [])), reverse=True)
        for n in god_sorted[:20]:
            nid    = n.get("id", "")
            name   = n.get("name") or nid
            ntype  = n.get("type", "node")[:2]  # fn/cl/md/me
            file_  = n.get("file", "")
            line_s = n.get("line_start")
            cid    = n.get("community")
            loc    = f"{file_}:{line_s}" if line_s else file_
            cluster = f" C{cid}" if cid is not None else ""
            sig    = _sig(n)

            chain   = _call_chain_compact(nid, edge_map, node_by_id)
            in_names = [
                (node_by_id.get(sid, {}).get("name") or sid)
                for sid, _ in sorted(reverse_edge_map.get(nid, []), key=lambda x: _EDGE_PRIORITY.get(x[1], 99))[:4]
            ]
            in_part  = f" ←{','.join(in_names)}" if in_names else ""
            out_part = f" {chain}" if chain else ""

            lines.append(f"{name}{sig} {ntype}{cluster} {loc}{out_part}{in_part}")
            doc = _docline(n)
            if doc:
                lines.append(f"  {doc}")

    # ── Cluster map — one line each with derived purpose label ─────────────────
    if communities:
        lines.append("\n## Clusters")
        for cid, members in sorted(communities.items(), key=lambda x: len(x[1]), reverse=True)[:12]:
            hub_flag  = "★" if any(n.get("is_god") for n in members) else ""
            purpose   = _cluster_purpose(cid, members)
            hub_names = [n.get("name") for n in members if n.get("is_god") and n.get("name")]
            rest      = [n.get("name") for n in members if not n.get("is_god") and n.get("name")]
            sample    = ",".join((hub_names + rest)[:6])
            lines.append(f"C{cid}({len(members)}{hub_flag} {purpose}) {sample}")

    # ── File index ─────────────────────────────────────────────────────────────
    file_lines = _file_index_lines(nodes, adj)
    if file_lines:
        lines.append("\n## File Index")
        lines += file_lines

    if orphan_count:
        lines.append(f"\n{orphan_count} orphan nodes omitted.")

    return lines


def _build_common_lines(ctx: dict) -> list[str]:
    nodes             = ctx["nodes"]
    edges             = ctx["edges"]
    god_nodes         = ctx["god_nodes"]
    orphan_count      = ctx["orphan_count"]
    lang_counter      = ctx["lang_counter"]
    communities       = ctx["communities"]
    type_counter      = ctx["type_counter"]
    edge_type_counter = ctx["edge_type_counter"]
    adj               = ctx["adj"]
    edge_map          = ctx["edge_map"]
    reverse_edge_map  = ctx["reverse_edge_map"]
    node_by_id        = ctx["node_by_id"]
    repo_url          = ctx["repo_url"]
    branch            = ctx["branch"]
    sha_short         = ctx["sha_short"]

    lines: list[str] = []

    lines += [
        "## Graph Summary",
        "",
        "| Property | Value |",
        "|----------|-------|",
        f"| Repository | `{repo_url}` |",
        f"| Branch | `{branch}` |",
        f"| Commit | `{sha_short}` |",
        f"| Total nodes | {len(nodes):,} |",
        f"| Total edges | {len(edges):,} |",
        f"| Communities | {len(communities)} |",
        f"| Hub nodes | {len(god_nodes)} |",
        f"| Orphan nodes | {orphan_count} |",
        "",
    ]

    if lang_counter:
        lines += ["## Languages", ""]
        for lang, count in lang_counter.most_common():
            pct = count / len(nodes) * 100 if nodes else 0
            lines.append(f"- **{lang}**: {count:,} nodes ({pct:.0f}%)")
        lines.append("")

    lines += ["## Node Types", ""]
    for ntype, count in type_counter.most_common():
        lines.append(f"- `{ntype}`: {count:,}")
    lines.append("")

    if god_nodes:
        lines += [
            "## Hub Nodes",
            "",
            "Architectural anchors (★) that span multiple communities.",
            "Each entry lists the full signature, docstring, and outbound (→) / inbound (←) edges",
            "so you can trace call chains through the graph without opening source files.",
            "",
        ]
        god_sorted = sorted(god_nodes, key=lambda n: len(adj.get(n.get("id", ""), [])), reverse=True)
        for n in god_sorted[:25]:
            nid    = n.get("id", "")
            name   = n.get("name") or nid
            ntype  = n.get("type", "node")
            file_  = n.get("file", "")
            line_s = n.get("line_start")
            line_e = n.get("line_end")
            cid    = n.get("community")
            degree = len(adj.get(nid, []))
            loc    = (
                f"{file_}:{line_s}-{line_e}" if (line_s and line_e) else
                f"{file_}:{line_s}" if line_s else file_
            )
            cid_tag = f" · cluster {cid}" if cid is not None else ""
            sig     = _sig(n)

            lines += [f"### ★ `{name}{sig}` (`{ntype}`) — `{loc}`{cid_tag} · {degree} connections", ""]

            doc = _docline(n)
            if doc:
                lines += [f"> {doc}", ""]

            outbound = sorted(edge_map.get(nid, []), key=lambda x: _EDGE_PRIORITY.get(x[1], 99))[:8]
            if outbound:
                lines.append("**→ Calls / depends on:**")
                for tid, etype in outbound:
                    tnode = node_by_id.get(tid)
                    tname = tnode.get("name", tid) if tnode else tid
                    tsig  = _sig(tnode) if tnode else ""
                    tfile = tnode.get("file", "") if tnode else ""
                    tline = tnode.get("line_start") if tnode else None
                    tloc  = f"{tfile}:{tline}" if tfile and tline else tfile or tid
                    # Show 1 level of sub-calls for the outbound target
                    sub = _call_chain_compact(tid, edge_map, node_by_id, max_out=3)
                    sub_part = f" {sub}" if sub else ""
                    lines.append(f"  - `{etype}` → `{tname}{tsig}` — `{tloc}`{sub_part}")

            inbound = sorted(reverse_edge_map.get(nid, []), key=lambda x: _EDGE_PRIORITY.get(x[1], 99))[:8]
            if inbound:
                lines.append("**← Called by / depended on by:**")
                for sid, etype in inbound:
                    snode = node_by_id.get(sid)
                    sname = snode.get("name", sid) if snode else sid
                    ssig  = _sig(snode) if snode else ""
                    sfile = snode.get("file", "") if snode else ""
                    sline = snode.get("line_start") if snode else None
                    sloc  = f"{sfile}:{sline}" if sfile and sline else sfile or sid
                    lines.append(f"  - `{etype}` ← `{sname}{ssig}` — `{sloc}`")

            lines.append("")

    # ── Critical call paths ────────────────────────────────────────────────────
    path_lines = _critical_path_lines(god_nodes, edge_map, node_by_id, adj)
    if path_lines:
        lines += ["## Critical Call Paths", ""]
        lines += path_lines
        lines.append("")

    if communities:
        lines += [
            "## Community Clusters",
            "",
            "Each cluster is a cohesive functional area identified by the Leiden algorithm.",
            "Nodes in the same cluster are strongly related by call and import edges.",
            "",
        ]
        for cid, members in sorted(communities.items(), key=lambda x: len(x[1]), reverse=True)[:15]:
            god_count = sum(1 for n in members if n.get("is_god"))
            purpose   = _cluster_purpose(cid, members)
            rep_names = [n.get("name") for n in members if n.get("is_god") and n.get("name")]
            rep = rep_names[0] if rep_names else (members[0].get("name") if members else f"cluster-{cid}")
            lines += [f"### Cluster {cid} — *{rep}* · {purpose} ({len(members)} members, {god_count} hubs)", ""]
            sorted_members = sorted(
                members,
                key=lambda n: (not n.get("is_god"), -len(adj.get(n.get("id", ""), []))),
            )
            for n in sorted_members[:20]:
                name   = n.get("name") or n.get("id", "")
                ntype  = n.get("type", "node")
                file_  = n.get("file", "")
                line_s = n.get("line_start")
                line_e = n.get("line_end")
                hub_tag = " ★" if n.get("is_god") else ""
                sig     = _sig(n)
                loc = (
                    f"{file_}:{line_s}-{line_e}" if (line_s and line_e) else
                    f"{file_}:{line_s}" if line_s else file_
                )
                lines.append(f"  - `{name}{sig}` (`{ntype}`){hub_tag} — `{loc}`")
            if len(members) > 20:
                lines.append(f"  - *…and {len(members) - 20} more*")
            lines.append("")

    # ── File index ─────────────────────────────────────────────────────────────
    file_lines = _file_index_lines(nodes, adj)
    if file_lines:
        lines += ["## File Index", ""]
        lines += file_lines
        lines.append("")

    if edge_type_counter:
        lines += ["## Relationship Types", ""]
        for etype, count in edge_type_counter.most_common():
            lines.append(f"- `{etype}`: {count:,} edges")
        lines.append("")

    return lines


# ── Helpers ────────────────────────────────────────────────────────────────────


_EDGE_PRIORITY: dict[str, int] = {
    "CALLS": 0, "IMPORTS": 1, "INHERITS": 2,
    "DECORATES": 3, "CONTAINS": 4, "RELATES_TO": 5, "DEPENDS_ON": 6,
}


def _sig(n: dict | None) -> str:
    """Return formatted signature: (p1, p2) -> RetType — empty string for non-callables."""
    if n is None:
        return ""
    ntype = n.get("type", "")
    if ntype not in ("function", "method"):
        return ""
    params = n.get("params") or []
    ret    = n.get("return_type")
    sig    = f"({', '.join(params)})" if params else "()"
    return f"{sig} -> {ret}" if ret else sig


def _docline(n: dict | None) -> str | None:
    """Return the first meaningful line of a node's docstring, truncated."""
    if n is None:
        return None
    doc = n.get("docstring")
    if not doc:
        return None
    first = doc.strip().splitlines()[0].strip()
    return first[:120] if first else None


def _call_chain_compact(
    nid: str,
    edge_map: dict[str, list[tuple[str, str]]],
    node_by_id: dict[str, dict],
    max_out: int = 4,
) -> str:
    """Return a 2-hop call chain: →A(→A1,A2),B,C  (CALLS edges only)."""
    hop1 = [
        (tid, etype)
        for tid, etype in sorted(
            edge_map.get(nid, []),
            key=lambda x: _EDGE_PRIORITY.get(x[1], 99),
        )[:max_out]
        if etype == "CALLS"
    ]
    if not hop1:
        return ""

    parts: list[str] = []
    for tid, _ in hop1:
        tname = node_by_id.get(tid, {}).get("name") or tid.split("::")[-1]
        sub = [
            node_by_id.get(stid, {}).get("name") or stid.split("::")[-1]
            for stid, setype in edge_map.get(tid, [])
            if setype == "CALLS"
        ][:3]
        parts.append(f"{tname}(→{','.join(sub)})" if sub else tname)

    return f"→{'|'.join(parts)}"


def _critical_path_lines(
    god_nodes: list[dict],
    edge_map: dict[str, list[tuple[str, str]]],
    node_by_id: dict[str, dict],
    adj: dict[str, list[str]],
    max_paths: int = 8,
    max_depth: int = 4,
) -> list[str]:
    """Derive the top call paths from hub nodes following CALLS edges.

    Each line is a human-readable path: `hub → A → B → C`
    Only paths of depth ≥ 2 are emitted (1-hop is already in hub listings).
    """
    lines: list[str] = []
    seen_paths: set[tuple[str, ...]] = set()

    # Sort hubs by degree descending so the most connected produce paths first.
    sorted_hubs = sorted(
        god_nodes,
        key=lambda n: len(adj.get(n.get("id", ""), [])),
        reverse=True,
    )

    for hub in sorted_hubs:
        if len(lines) >= max_paths:
            break
        hid = hub.get("id", "")

        # BFS — follow CALLS only, stop at max_depth hops.
        queue: list[list[str]] = [[hid]]
        while queue and len(lines) < max_paths:
            path = queue.pop(0)
            nid = path[-1]
            calls = [
                tid
                for tid, etype in edge_map.get(nid, [])
                if etype == "CALLS" and tid not in path
            ][:3]

            if not calls and len(path) >= 2:
                key = tuple(path)
                if key not in seen_paths:
                    seen_paths.add(key)
                    names = [
                        node_by_id.get(i, {}).get("name") or i.split("::")[-1]
                        for i in path
                    ]
                    lines.append(f"- `{'` → `'.join(names)}`")
                continue

            for tid in calls:
                new_path = path + [tid]
                if len(new_path) - 1 >= max_depth:
                    key = tuple(new_path)
                    if key not in seen_paths:
                        seen_paths.add(key)
                        names = [
                            node_by_id.get(i, {}).get("name") or i.split("::")[-1]
                            for i in new_path
                        ]
                        lines.append(f"- `{'` → `'.join(names)}`")
                else:
                    queue.append(new_path)

    return lines


def _file_index_lines(
    nodes: list[dict],
    adj: dict[str, list[str]],
    max_files: int = 30,
) -> list[str]:
    """Return file-to-cluster lines: `file → C<id>[★]: hub1★, fn2, fn3 [+N]`"""
    # Group non-external nodes by file.
    file_nodes: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        f = n.get("file")
        if f and n.get("type") != "external":
            file_nodes[f].append(n)

    if not file_nodes:
        return []

    lines: list[str] = []

    # Determine primary cluster per file (majority vote).
    for filepath in sorted(file_nodes)[:max_files]:
        members = file_nodes[filepath]
        cids = [n.get("community") for n in members if n.get("community") is not None]
        primary_cid = Counter(cids).most_common(1)[0][0] if cids else None
        has_hub = any(n.get("is_god") for n in members)
        cid_tag = f"C{primary_cid}{'★' if has_hub else ''}" if primary_cid is not None else "C?"

        # Sort: hubs first, then by degree.
        sorted_members = sorted(
            members,
            key=lambda n: (not n.get("is_god"), -len(adj.get(n.get("id", ""), []))),
        )
        # Skip pure module nodes in the listing (they don't add info).
        displayable = [n for n in sorted_members if n.get("type") != "module"]
        shown = displayable[:5]
        rest_count = len(displayable) - len(shown)

        parts = []
        for n in shown:
            nm = n.get("name") or "?"
            hub_mark = "★" if n.get("is_god") else ""
            parts.append(f"{nm}{hub_mark}")

        label = ", ".join(parts)
        if rest_count > 0:
            label += f" [+{rest_count}]"

        lines.append(f"{filepath} → {cid_tag}: {label}")

    return lines


def _cluster_purpose(cid: int | str, members: list[dict]) -> str:
    """Derive a short purpose label from cluster membership.

    Attempts: common path prefix → hub node name → fallback.
    """
    files = [n.get("file", "") for n in members if n.get("file")]
    prefix = ""
    if files:
        parts_list = [Path(f).parts for f in files if f]
        if parts_list:
            common: list[str] = []
            for level in zip(*parts_list):
                if len(set(level)) == 1:
                    common.append(level[0])
                else:
                    break
            # Skip the root "." part; keep up to 2 directory segments.
            meaningful = [p for p in common if p not in (".", "/")]
            prefix = "/".join(meaningful[:2])

    hubs = [n.get("name") for n in members if n.get("is_god") and n.get("name")]
    if hubs and prefix:
        return f"{prefix}·{hubs[0]}"
    if hubs:
        return hubs[0]
    if prefix:
        return prefix
    return f"cluster-{cid}"


def _extract_stats(nodes: list[dict], edges: list[dict]) -> dict:
    god_nodes    = [n for n in nodes if n.get("is_god")]
    orphan_count = sum(1 for n in nodes if n.get("is_orphan"))

    lang_counter: Counter[str] = Counter()
    for n in nodes:
        lang = n.get("language")
        if lang:
            lang_counter[lang] += 1

    communities: dict[int, list[dict]] = defaultdict(list)
    for n in nodes:
        cid = n.get("community")
        if cid is not None:
            communities[int(cid)].append(n)

    adj: dict[str, list[str]] = defaultdict(list)
    edge_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
    reverse_edge_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in edges:
        s, t = e.get("source"), e.get("target")
        etype = e.get("type", "?")
        if s and t:
            adj[s].append(t)
            adj[t].append(s)
            edge_map[s].append((t, etype))
            reverse_edge_map[t].append((s, etype))

    node_by_id: dict[str, dict] = {n["id"]: n for n in nodes if n.get("id")}

    return dict(
        god_nodes=god_nodes,
        orphan_count=orphan_count,
        lang_counter=lang_counter,
        communities=dict(communities),
        type_counter=Counter(n.get("type", "unknown") for n in nodes),
        edge_type_counter=Counter(e.get("type", "unknown") for e in edges),
        adj=dict(adj),
        edge_map=dict(edge_map),
        reverse_edge_map=dict(reverse_edge_map),
        node_by_id=node_by_id,
    )


_LANG_GLOBS: dict[str, str] = {
    "python": "**/*.py", "typescript": "**/*.ts", "javascript": "**/*.js",
    "java": "**/*.java", "go": "**/*.go", "rust": "**/*.rs", "cpp": "**/*.cpp",
    "c": "**/*.c", "csharp": "**/*.cs", "ruby": "**/*.rb", "php": "**/*.php",
    "kotlin": "**/*.kt", "swift": "**/*.swift", "scala": "**/*.scala",
}


def _lang_globs(lang_counter: Counter) -> list[str]:
    return [_LANG_GLOBS[lang] for lang in lang_counter if lang.lower() in _LANG_GLOBS]


def _repo_slug(repo_url: str) -> str:
    slug = re.sub(r"^https?://github\.com/", "", repo_url)
    return re.sub(r"\.git$", "", slug)
