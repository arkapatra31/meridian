# What is Meridian?

Meridian is a remote-first, agent-powered code knowledge graph builder. A user points it at any GitHub repository URL and gets back an interactive, queryable knowledge graph — no local installation required on the user's end.

Meridian is proprietary software. All rights reserved. No part of this codebase may be reproduced, distributed, or used without explicit written consent.

## Core Value Proposition

- **Zero install for end users** — just provide a GitHub URL (and PAT for private repos)
- **Two-pass parsing** — tree-sitter (deterministic, free) + agent reasoning (surgical, targeted)
- **Built-in differential updates** — incremental graph patches in seconds, not full rebuilds
- **Agent SDK with tool use** — grep/glob/read for precise cross-file resolution without polluting context
- **QnA grounded in the graph** — answers cite specific nodes and files, not hallucinated references

## Architecture Overview

Meridian has four layers with 12 components total.

### Layer 1: Ingestion

| Component | Technology | Role |
|-----------|-----------|------|
| API Gateway (C1) | FastAPI | REST endpoints, WebSocket for build progress, serves React SPA |
| GitHub MCP Server (C2) | GitHub MCP | All GitHub interaction — clone, pull, diff, metadata, PRs, issues |
| Repo Cache (C3) | Server filesystem | Stores git clones at `/var/meridian/repos/{repo_hash}/` |

**API endpoints:**
- `POST /repos` — submit a repo for graph building (accepts `url`, optional `pat`, optional `branch`)
- `GET /repos/{id}/graph` — fetch the graph JSON
- `POST /repos/{id}/query` — send a QnA question
- `POST /repos/{id}/sync` — trigger incremental update
- `WS /repos/{id}/status` — stream build progress to frontend

**Repo cache structure:**
```
/var/meridian/repos/{repo_hash}/
├── .git/
├── src/
├── ...
└── .meridian/
    ├── last_commit_sha
    ├── file_hashes.json
    └── graph.json
```

### Layer 2: Processing

| Component | Technology | Role |
|-----------|-----------|------|
| Agent SDK Orchestrator (C4) | Claude Code Agent SDK | Coordinates entire pipeline, makes build vs update decisions |
| Tree-sitter (C5) | py-tree-sitter + grammar .so files | Pass 1: deterministic AST extraction across 25 languages |
| Agent Reasoning (C6) | Agent SDK with tools | Pass 2: resolves ambiguous edges using grep/glob/read |
| Diff Engine (C7) | git diff + internal logic | Detects changed files, scopes re-processing |

**Pass 1 — Tree-sitter (deterministic, free, fast):**
- Parses all source files into ASTs
- Extracts nodes: modules, classes, functions, methods
- Extracts EXTRACTED edges: imports, calls (same-file), contains, inherits, decorates
- Flags ambiguous references (unresolved cross-file imports, dynamic calls) for Pass 2
- Supports 25 languages: Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, Ruby, C#, Kotlin, Scala, PHP, Swift, Lua, Zig, Dart, Elixir, Vue, Svelte, and more
- Performance: ~10,000 files/sec

**Pass 2 — Agent Reasoning (targeted, surgical):**
- ONLY fires for edges tree-sitter flagged as ambiguous
- Uses glob to find candidate files, grep to locate definitions, read to load specific line ranges
- This surgical tool use loads only 2-3 files per resolution — does NOT pollute the full context
- Resolves: cross-file imports, dynamic dispatch, getattr patterns, decorator-based routing, plugin registries
- Produces INFERRED edges with the resolution reasoning
- For clean codebases: ~10-15% of edges need agent resolution
- For metaprogramming-heavy codebases: ~30-40%

**Key design principle:** The agent's grep/glob/read tool pattern is an active ADVANTAGE over alternatives like LSP. It loads only what's needed (surgical), handles dynamic patterns LSP cannot (flexible), and costs scale with ambiguity not project size (efficient).

**Diff Engine — incremental update flow:**
1. `git pull` via GitHub MCP
2. `git diff last_commit_sha..HEAD --name-status`
3. Categorize: added, modified, deleted, renamed
4. Added files: tree-sitter parse + agent resolve + add nodes/edges
5. Modified files: tree-sitter re-parse + diff old vs new edges + patch
6. Deleted files: remove all nodes/edges from that file
7. Renamed files: update file references, preserve edges
8. Re-evaluate neighbor edges (anything touching a changed node)
9. Re-cluster only affected Leiden communities
10. Update `last_commit_sha`

### Layer 3: Graph

| Component | Technology | Role |
|-----------|-----------|------|
| Graph Builder (C8) | NetworkX | Merges EXTRACTED + INFERRED edges into unified graph |
| Leiden Clustering (C9) | graspologic | Community detection on graph topology, no embeddings |
| Graph Store (C10) | JSON file | Persists the knowledge graph per repo |

**Node schema:**
```json
{
  "id": "src/auth/tokens.py::validate_token",
  "type": "function",
  "name": "validate_token",
  "file": "src/auth/tokens.py",
  "line_start": 42,
  "line_end": 67,
  "language": "python",
  "params": ["token: str"],
  "docstring": "Validates a JWT token and returns the user payload.",
  "community": 3
}
```
Node types: `module`, `class`, `function`, `method`

**Edge schema:**
```json
{
  "source": "src/routes/api.py::login",
  "target": "src/auth/tokens.py::validate_token",
  "type": "CALLS",
  "confidence": "EXTRACTED",
  "weight": 1.0,
  "metadata": {}
}
```
Edge types: `IMPORTS`, `CALLS`, `CONTAINS`, `INHERITS`, `DECORATES`, `RELATES_TO`, `DEPENDS_ON`
Confidence levels: `EXTRACTED` (tree-sitter, high trust), `INFERRED` (agent, medium trust)

**Graph store (graph.json) top-level schema:**
```json
{
  "metadata": {
    "repo_url": "...",
    "branch": "main",
    "last_commit_sha": "a1b2c3d4",
    "built_at": "2026-04-26T10:30:00Z",
    "node_count": 847,
    "edge_count": 2341,
    "community_count": 12,
    "languages": ["python", "typescript", "go"]
  },
  "nodes": [],
  "edges": [],
  "communities": {
    "0": { "label": "Auth cluster", "node_count": 34 }
  },
  "god_nodes": ["src/db/connection.py::get_db"],
  "surprises": [
    { "edge": "...", "reason": "Unexpected auth→payment link" }
  ]
}
```

**Leiden clustering configuration:**
- Implementation: graspologic (Microsoft)
- Resolution parameter: 1.0 (tune per repo size)
- Quality function: modularity (CPM for very large repos)
- Iterations: until convergence (typically 2-4)
- Post-clustering: identifies god nodes (highest-degree bridging nodes), surprise edges (unexpected cross-community connections), orphan nodes (potential dead code)

### Layer 4: Output

| Component | Technology | Role |
|-----------|-----------|------|
| QnA Agent (C11) | ClaudeSDKClient | Answers questions grounded in graph subgraph context |
| React Frontend (C12) | React + react-force-graph (WebGL) | Interactive graph visualization with semantic zoom |

**QnA flow:**
1. User asks a question
2. Load graph.json
3. BFS from nodes matching the query keywords — extract 2-hop neighborhood subgraph
4. Serialize subgraph as context (~2k tokens, NOT the full repo)
5. Send to ClaudeSDKClient with system prompt enforcing graph-grounded answers
6. Return answer with references to specific graph nodes and files

**Why ClaudeSDKClient and NOT Agent SDK for QnA:**
- QnA does not need tools (no grep/read/glob) — the graph IS the context
- Single completion call, no tool loop — lower latency
- Lower cost: one API call, not multiple agent steps

**React frontend features:**
- Force-directed layout with WebGL rendering (handles 5k+ nodes)
- Nodes colored by Leiden community
- Edge thickness encodes confidence (EXTRACTED thicker, INFERRED thinner)
- Semantic zoom: zoomed out = community super-nodes, mid = god nodes + boundaries, zoomed in = all nodes with labels
- Click node = sidebar with function details, docstring, file link
- Search bar filters/highlights nodes
- QnA panel: ask question, answer highlights relevant subgraph nodes

**Frontend libraries:**
- react-force-graph-3d (WebGL graph rendering)
- zustand (state management)
- tailwindcss (styling)

## Deployment

Single Docker image. No database, no Redis, no message queue.

**Container contents:**
- FastAPI server (API gateway + static React SPA serving)
- py-tree-sitter + 25 language grammar .so files
- Agent SDK runtime
- ClaudeSDKClient runtime
- NetworkX + graspologic

**Volume mount:** `/var/meridian/repos` — stores git clones and graph.json files

**External dependencies (network):**
- GitHub API (via MCP server) — for repo cloning, diffs, metadata
- Anthropic API — for Agent SDK (orchestration + Pass 2) and ClaudeSDKClient (QnA)

**Repo cache lifecycle:**
- Created on first `POST /repos`
- Updated via `git pull` on `POST /repos/{id}/sync`
- Evicted after configurable TTL (default: 7 days idle)
- Disk budget per instance (default: 50GB), LRU eviction when full

## Key Design Decisions

1. **No LSP** — We explicitly chose NOT to use Language Server Protocol. The Agent SDK's grep/glob/read tools provide surgical cross-file resolution that handles dynamic patterns LSP cannot, loads only needed context, and requires no language-server infrastructure.

2. **Tree-sitter over Python ast** — Tree-sitter supports 25 languages vs Python ast's Python-only limitation. This makes Meridian a general-purpose tool, not a Python-only niche.

3. **GitHub MCP as sole data access** — All GitHub interaction flows through the MCP server. No component talks to GitHub directly. This centralizes auth, rate limiting, and caching.

4. **Agent SDK for orchestration, ClaudeSDKClient for QnA** — Different tools for different jobs. Orchestration needs tool use; QnA needs single-shot completion with graph context.

5. **JSON file storage over database** — graph.json is simple, portable, and sufficient for per-repo knowledge graphs. No database dependency to manage.

6. **Differential updates from day one** — Not an afterthought. The diff engine is a core component, not a bolted-on optimization.

7. **Two confidence tiers** — Every edge is tagged EXTRACTED (tree-sitter, deterministic) or INFERRED (agent, probabilistic). This transparency is surfaced in both the QnA answers and the frontend visualization.

## Cost Model

| Component | Cost |
|-----------|------|
| Tree-sitter (Pass 1) | Free — local, deterministic |
| Diff engine (C7) | Free — local git operations |
| Graph builder + Leiden | Free — local CPU |
| Agent SDK (Pass 2) | Token cost — per ambiguous edge resolution |
| Agent SDK (orchestration) | Token cost — pipeline coordination |
| ClaudeSDKClient (QnA) | Token cost — per user query |
| Server compute | Infrastructure cost — Docker container |
| Disk storage | Infrastructure cost — repo clones + graph files |

**Optimization principle:** Tree-sitter handles ~80% of edges for free. Agent tokens only burn on the ~20% that genuinely need reasoning. On incremental updates, only changed-file edges incur agent cost.

## Security Considerations

- GitHub PATs must be handled carefully — minimum required scopes, never logged, never stored beyond the session
- Private repo code is cloned to server disk — ensure proper isolation between users
- Repo clones must be cleaned up on TTL expiry
- No telemetry, no usage tracking, no analytics
- The only outbound network calls are to GitHub API (via MCP) and Anthropic API (Agent SDK + ClaudeSDKClient)

## File Structure (Target)

```
meridian/
├── CLAUDE.md                  # This file
├── LICENSE                    # Proprietary — All Rights Reserved
├── README.md
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── src/
│   ├── api/                   # C1: FastAPI gateway
│   │   ├── main.py
│   │   ├── routes.py
│   │   └── websocket.py
│   ├── ingestion/             # C2, C3: GitHub MCP + repo cache
│   │   ├── github_mcp.py
│   │   └── repo_cache.py
│   ├── processing/            # C4, C5, C6, C7: Agent + tree-sitter + diff
│   │   ├── orchestrator.py    # C4: Agent SDK orchestration
│   │   ├── treesitter.py      # C5: tree-sitter extraction
│   │   ├── agent_pass.py      # C6: agent reasoning with tools
│   │   └── diff_engine.py     # C7: incremental update logic
│   ├── graph/                 # C8, C9, C10: NetworkX + Leiden + store
│   │   ├── builder.py         # C8: graph construction
│   │   ├── clustering.py      # C9: Leiden community detection
│   │   └── store.py           # C10: JSON persistence
│   ├── qna/                   # C11: QnA agent
│   │   ├── agent.py
│   │   └── subgraph.py        # BFS subgraph extraction
│   └── shared/
│       ├── schemas.py         # Node, Edge, Graph dataclasses
│       └── config.py          # Environment config
├── frontend/                  # C12: React app
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── GraphView.tsx
│   │   │   ├── QnAPanel.tsx
│   │   │   ├── NodeSidebar.tsx
│   │   │   └── SearchBar.tsx
│   │   └── stores/
│   │       └── graphStore.ts  # zustand store
│   └── tailwind.config.js
├── grammars/                  # Tree-sitter .so files
│   ├── python.so
│   ├── javascript.so
│   ├── typescript.so
│   └── ...
└── tests/
    ├── test_treesitter.py
    ├── test_agent_pass.py
    ├── test_diff_engine.py
    ├── test_graph_builder.py
    └── test_qna.py
```

## Commands Reference

When building Meridian, use these as the target CLI / API commands:

```bash
# API usage (via curl or frontend)
POST /repos                    # Submit repo for graph building
GET  /repos/{id}/graph         # Get the knowledge graph
POST /repos/{id}/query         # Ask a question
POST /repos/{id}/sync          # Trigger incremental update
WS   /repos/{id}/status        # Stream build progress
```

## What NOT to Do

- Do NOT use LSP or language servers — we explicitly decided against this
- Do NOT use Python's built-in `ast` module — tree-sitter replaces it for multi-language support
- Do NOT use the Anthropic API directly — use Claude Code Agent SDK for orchestration and ClaudeSDKClient for QnA
- Do NOT add a database (PostgreSQL, Redis, etc.) — JSON file persistence is the design choice
- Do NOT send full repo contents to the LLM — always use surgical grep/glob/read tool calls
- Do NOT rebuild the full graph on sync — always use the diff engine for incremental updates
- Do NOT make the frontend a separate deployment — it ships as a static build served by FastAPI