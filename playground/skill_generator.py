"""Generate context/skill files for AI coding tools from a Meridian knowledge graph.

Supported tools
---------------
claude_code  → .claude/skills/<slug>/SKILL.md        (skill directory, frontmatter)
cursor       → .cursor/rules/<slug>-context.mdc       (MDC frontmatter + markdown)
copilot      → .github/copilot-instructions.md        (plain markdown, always-on)
windsurf     → .windsurf/rules/meridian-<slug>.md     (trigger frontmatter, always-on)
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
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


def skill_slug(repo_url: str) -> str:
    """Return the kebab-case skill directory name for a Claude Code skill."""
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", _repo_slug(repo_url))
    return f"meridian-{safe}"


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
        return f".claude/skills/{skill_slug(repo_url)}/{fname}"
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
        "Answer from this graph. No source reads for structural questions.",
        "Cite: `name (file:line)`. Lookup → Hubs first, then Clusters.",
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
    """Ultra-compact body: one line per hub, one line per cluster.

    Format is optimised for LLM consumption, not human reading. Every token
    carries information — no markdown bold, no decorative separators.

    Hub line:   name type Ccluster file:line →callee1,callee2 ←caller1,caller2
    Cluster:    Cid(count★) hub1,hub2,member3,member4,member5
    """
    god_nodes        = ctx["god_nodes"]
    orphan_count     = ctx["orphan_count"]
    communities      = ctx["communities"]
    adj              = ctx["adj"]
    edge_map         = ctx["edge_map"]
    reverse_edge_map = ctx["reverse_edge_map"]
    node_by_id       = ctx["node_by_id"]

    lines: list[str] = []

    # ── Hub nodes — one line each ──────────────────────────────────────────────
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

            out_names = [
                (node_by_id.get(tid, {}).get("name") or tid)
                for tid, _ in sorted(edge_map.get(nid, []), key=lambda x: _EDGE_PRIORITY.get(x[1], 99))[:5]
            ]
            in_names = [
                (node_by_id.get(sid, {}).get("name") or sid)
                for sid, _ in sorted(reverse_edge_map.get(nid, []), key=lambda x: _EDGE_PRIORITY.get(x[1], 99))[:5]
            ]

            out_part = f" →{','.join(out_names)}" if out_names else ""
            in_part  = f" ←{','.join(in_names)}"  if in_names  else ""
            lines.append(f"{name} {ntype}{cluster} {loc}{out_part}{in_part}")

    # ── Cluster map — one line each ────────────────────────────────────────────
    if communities:
        lines.append("\n## Clusters")
        for cid, members in sorted(communities.items(), key=lambda x: len(x[1]), reverse=True)[:12]:
            hub_flag  = "★" if any(n.get("is_god") for n in members) else ""
            hub_names = [n.get("name") for n in members if n.get("is_god") and n.get("name")]
            rest      = [n.get("name") for n in members if not n.get("is_god") and n.get("name")]
            sample    = ",".join((hub_names + rest)[:6])
            lines.append(f"C{cid}({len(members)}{hub_flag}) {sample}")

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
            "Each entry lists outbound (→) and inbound (←) edges so you can trace call chains",
            "through the graph without opening source files.",
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
            lines += [f"### ★ `{name}` (`{ntype}`) — `{loc}`{cid_tag} · {degree} connections", ""]

            outbound = sorted(edge_map.get(nid, []), key=lambda x: _EDGE_PRIORITY.get(x[1], 99))[:8]
            if outbound:
                lines.append("**→ Calls / depends on:**")
                for tid, etype in outbound:
                    tnode = node_by_id.get(tid)
                    tname = tnode.get("name", tid) if tnode else tid
                    tfile = tnode.get("file", "") if tnode else ""
                    tline = tnode.get("line_start") if tnode else None
                    tloc  = f"{tfile}:{tline}" if tfile and tline else tfile or tid
                    lines.append(f"  - `{etype}` → `{tname}` — `{tloc}`")

            inbound = sorted(reverse_edge_map.get(nid, []), key=lambda x: _EDGE_PRIORITY.get(x[1], 99))[:8]
            if inbound:
                lines.append("**← Called by / depended on by:**")
                for sid, etype in inbound:
                    snode = node_by_id.get(sid)
                    sname = snode.get("name", sid) if snode else sid
                    sfile = snode.get("file", "") if snode else ""
                    sline = snode.get("line_start") if snode else None
                    sloc  = f"{sfile}:{sline}" if sfile and sline else sfile or sid
                    lines.append(f"  - `{etype}` ← `{sname}` — `{sloc}`")

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
            rep_names = [n.get("name") for n in members if n.get("is_god") and n.get("name")]
            rep = rep_names[0] if rep_names else (members[0].get("name") if members else f"cluster-{cid}")
            lines += [f"### Cluster {cid} — *{rep}* ({len(members)} members, {god_count} hubs)", ""]
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
                loc = (
                    f"{file_}:{line_s}-{line_e}" if (line_s and line_e) else
                    f"{file_}:{line_s}" if line_s else file_
                )
                lines.append(f"  - `{name}` (`{ntype}`){hub_tag} — `{loc}`")
            if len(members) > 20:
                lines.append(f"  - *…and {len(members) - 20} more*")
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
