"""Generate context/skill files for AI coding tools from a Meridian knowledge graph.

Supported tools
---------------
claude_code  → .claude/commands/<slug>.md      (slash command, frontmatter)
cursor       → .cursor/rules/<slug>-context.mdc (MDC frontmatter + markdown)
copilot      → .github/copilot-instructions.md  (plain markdown, always-on)
windsurf     → .windsurfrules                   (plain markdown, always-on)
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


def skill_filename(repo_url: str, tool: str = TOOL_CLAUDE_CODE) -> str:
    """Return the suggested filename for the generated file."""
    slug = _repo_slug(repo_url)
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", slug)
    if tool == TOOL_CURSOR:
        return f"{safe}-context.mdc"
    if tool == TOOL_COPILOT:
        return "copilot-instructions.md"
    if tool == TOOL_WINDSURF:
        return ".windsurfrules"
    return f"meridian-{safe}.md"


def skill_placement_path(repo_url: str, tool: str = TOOL_CLAUDE_CODE) -> str:
    """Return the path (relative to repo root) where the file should be placed."""
    fname = skill_filename(repo_url, tool)
    if tool == TOOL_CLAUDE_CODE:
        return f".claude/commands/{fname}"
    if tool == TOOL_CURSOR:
        return f".cursor/rules/{fname}"
    if tool == TOOL_COPILOT:
        return f".github/{fname}"
    return fname  # windsurf → repo root (.windsurfrules)


# ── Format generators ──────────────────────────────────────────────────────────


def _generate_claude_code(ctx: dict) -> str:
    repo_slug = ctx["repo_slug"]
    lines: list[str] = []

    lines += [
        "---",
        f"description: Navigate {repo_slug} — search nodes, trace call chains, explore clusters",
        "---",
        "",
        f"# Meridian · {repo_slug}",
        "",
        f"You are navigating the **{repo_slug}** codebase using a Meridian knowledge graph.",
        "Use the context below to answer questions, trace call chains, and identify architectural patterns.",
        "",
        "---",
        "",
    ]

    lines += _build_common_lines(ctx)

    lines += [
        "---",
        "",
        "## How to Use This Context",
        "",
        "When answering questions about this codebase:",
        "",
        "1. **Start with hub nodes** — highest-connectivity anchors; trace outward from them.",
        "2. **Follow edge types** — `CALLS` = runtime dependency; `IMPORTS` = module dependency; `CONTAINS` = nesting.",
        "3. **Respect communities** — nodes in the same cluster are functionally cohesive.",
        "4. **Orphan nodes** have no connections — candidates for dead code or standalone utilities.",
        "5. **`INFERRED` edges** were resolved by an agent (less certain than `EXTRACTED` / tree-sitter).",
        "",
        "### Node schema",
        "```",
        'id:         "<file>::<name>"  — unique node identifier',
        "type:       module | class | function | method | external",
        "name:       short identifier",
        "file:       relative path from repo root",
        "line_start / line_end: int",
        "language:   string",
        "community:  int   — Leiden cluster ID",
        "is_god:     bool  — hub spanning 2+ communities",
        "is_orphan:  bool  — no connections (dead code candidate)",
        "```",
        "",
        "### Edge schema",
        "```",
        "source / target: node id",
        "type:       IMPORTS | CALLS | CONTAINS | INHERITS | DECORATES | RELATES_TO | DEPENDS_ON",
        "confidence: EXTRACTED (tree-sitter) | INFERRED (agent)",
        "```",
        "",
        f"*Graph ID: `{ctx['graph_id']}` · Generated by Meridian*",
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
            "## Hub Nodes (Architectural Anchors)",
            "",
            "These nodes span multiple communities and are the highest-leverage entry points.",
            "Start here when tracing unfamiliar call chains or imports.",
            "",
        ]
        god_sorted = sorted(god_nodes, key=lambda n: len(adj.get(n.get("id", ""), [])), reverse=True)
        for n in god_sorted[:25]:
            nid    = n.get("id", "")
            name   = n.get("name") or nid
            ntype  = n.get("type", "node")
            file_  = n.get("file", "")
            line_s = n.get("line_start")
            cid    = n.get("community")
            degree = len(adj.get(nid, []))
            loc    = f"{file_}:{line_s}" if line_s else file_
            cid_tag = f" · cluster {cid}" if cid is not None else ""
            lines.append(f"- **`{name}`** (`{ntype}`) — `{loc}` · {degree} connections{cid_tag}")
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
            for n in sorted_members[:10]:
                name   = n.get("name") or n.get("id", "")
                ntype  = n.get("type", "node")
                file_  = n.get("file", "")
                line_s = n.get("line_start")
                hub_tag = " ★" if n.get("is_god") else ""
                loc = f"{file_}:{line_s}" if line_s else file_
                lines.append(f"  - `{name}` (`{ntype}`){hub_tag} — `{loc}`")
            if len(members) > 10:
                lines.append(f"  - *…and {len(members) - 10} more*")
            lines.append("")

    if edge_type_counter:
        lines += ["## Relationship Types", ""]
        for etype, count in edge_type_counter.most_common():
            lines.append(f"- `{etype}`: {count:,} edges")
        lines.append("")

    return lines


# ── Helpers ────────────────────────────────────────────────────────────────────


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
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s and t:
            adj[s].append(t)
            adj[t].append(s)

    return dict(
        god_nodes=god_nodes,
        orphan_count=orphan_count,
        lang_counter=lang_counter,
        communities=dict(communities),
        type_counter=Counter(n.get("type", "unknown") for n in nodes),
        edge_type_counter=Counter(e.get("type", "unknown") for e in edges),
        adj=dict(adj),
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
