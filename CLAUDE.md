# CLAUDE.md — Meridian

## What is Meridian?

Meridian is a remote-first, agent-powered code knowledge graph builder. A user points it at any GitHub repository URL and gets back an interactive, queryable knowledge graph — no local installation required on the user's end.

Meridian is proprietary software. All rights reserved. No part of this codebase may be reproduced, distributed, or used without explicit written consent.

## Core Value Proposition

- **Zero install for end users** — just provide a GitHub URL (and PAT for private repos)
- **Two-pass parsing** — tree-sitter (deterministic, free) + agent reasoning (surgical, targeted)
- **Built-in differential updates** — incremental graph patches in seconds, not full rebuilds
- **Agent SDK with tool use** — grep/glob/read for precise cross-file resolution without polluting context
- **QnA grounded in the graph** — answers cite specific nodes and files, not hallucinated references

## Architecture Overview

Meridian is structured as **eight top-level components (C1–C8)**. Multi-unit components use sub-letters (e.g. `C3a`, `C4b`). The conceptual layers — ingestion, orchestration, parsing, graph, output, persistence — are reflected in the grouping below; canonical addressing is by component number.

| C# | Component | Path | Status |
|----|-----------|------|--------|
| C1 | API Gateway | `api/` | built |
| C2 | Orchestrator | `orchestrator/` | built |
| C3 | Ingestion Layer | `ingestion_layer/` | partial |
| ↳ C3a | Git Client | `ingestion_layer/repo_cache/clone_repo.py` | built |
| ↳ C3b | GitHub MCP Server | (not yet built) | TODO |
| C4 | Hybrid Parser | `hybrid_parsing/` | built |
| ↳ C4a | Tree-sitter (Pass 1) | `hybrid_parsing/codebase_parser/` | built |
| ↳ C4b | Agent Reasoning (Pass 2) | `hybrid_parsing/surgical_agent/` | built |
| ↳ C4c | Tree Indexer | `hybrid_parsing/tree_indexer/` | built |
| C5 | Graph Engine | `graph_engine/` | built |
| ↳ C5a | Graph Builder | `graph_engine/networkX_graph_builder/` | built |
| ↳ C5b | Leiden Clustering | `graph_engine/leiden_clustering/` | built |
| C6 | QnA Agent | (not yet built) | TODO |
| C7 | React Frontend | (not yet built) | TODO |
| C8 | Persistence (SQLite) | `db/` (`meridian.db`) | built |

### C1 — API Gateway

**Tech:** FastAPI.

**Role:** REST endpoints, WebSocket for build progress, serves the React SPA. Validates requests and delegates to the orchestrator (C2) — never calls ingestion (C3), parser (C4), or graph engine (C5) primitives directly.

**API endpoints:**
- `POST /auth/register` — create a new user account
- `POST /auth/login` — authenticate, returns JWT token
- `POST /repos` — submit a repo for graph building (accepts `url`, optional `pat`, optional `branch`)
- `GET /repos` — list all graphs owned by the authenticated user
- `GET /repos/{graph_id}/graph` — fetch the graph JSON
- `POST /repos/{graph_id}/query` — send a QnA question
- `POST /repos/{graph_id}/sync` — trigger incremental update
- `DELETE /repos/{graph_id}` — permanently delete a graph (explicit only, no auto-delete)
- `WS /repos/{graph_id}/status` — stream build progress to frontend

All `/repos` endpoints require a valid JWT token. Users can only access their own graphs.

### C2 — Orchestrator

**Tech:** Claude Code Agent SDK.

**Role:** Coordinates the entire pipeline and makes the FULL-vs-PATCH build decision. The single entry point invoked by C1.

- Lives in `orchestrator/orchestrator.py`. Entry point: `sync_repo(repo_url, pat, branch) -> OrchestrationResult`.
- Reads `has_active_graph(repo_url, branch)` from `orchestrator/utils/db_utils.py` to pick FULL vs PATCH; writes the audit row via `record_sync_run(...)` from the same module at the end of each build.
- C3, C4, and C5 own only primitives. All routing decisions — FULL vs PATCH, which DB rows to consult, which stages to chain — live here.

### C3 — Ingestion Layer

**CRITICAL — Hybrid ingestion model (rate-limit protection):**

The GitHub MCP server translates every tool call into an individual GitHub REST API request. GitHub enforces a rate limit of 5,000 requests/hour per PAT-authenticated user (shared across ALL tools using that PAT). Using the MCP's `get_file_contents` for bulk file fetching on a 500-file repo would consume 500+ API calls for a single build — making multi-repo or multi-user scenarios unusable.

**Solution: split bulk data from metadata.**

- **Initial build:** Use `git clone` directly via subprocess. This uses git's smart transfer protocol, NOT the REST API. One operation, all files on disk, zero API calls consumed. Tree-sitter and agent tools then read from the local filesystem. The clone is ephemeral — it can be evicted once the graph is built and persisted to the DB.
- **Incremental updates:** Use `git pull` (subprocess, not MCP) to fetch changes, then GitHub MCP only for the diff metadata (`compare_commits`) — typically 1-2 API calls.
- **Enrichment:** Use GitHub MCP for PR descriptions, issue context, contributor data, and code search. These are low-volume, high-value calls (5-20 per sync) that stay well within rate limits.

```
Initial build:  git clone (subprocess) → 0 API calls → rate limit safe
Incremental:    git pull (subprocess) + MCP diff → 2-5 API calls
Enrichment:     MCP PRs/issues/contributors → 5-20 API calls
────────────────────────────────────────────────────────────
Total per sync: ~10-25 API calls (vs 500-2000+ with MCP-only)
```

#### C3a — Git Client

**Tech:** git CLI invoked via subprocess.

**Role:** Initial clone + pull via the git protocol — zero API rate-limit impact. Driven by C2.

Writes the working copy to the ephemeral filesystem cache at `/var/meridian/cache/{repo_hash}/`:

```
/var/meridian/cache/{repo_hash}/
├── .git/
├── src/
└── ...
```

The cache is purely ephemeral. Graph data is persisted to C8 (the SQLite DB), NOT to the filesystem. Clones can be evicted at any time without data loss; the `repo_clones` row in C8 retains the `last_commit_sha` as a tombstone so a re-clone can resume cleanly.

#### C3b — GitHub MCP Server

**Tech:** GitHub MCP. **Status:** not yet built.

**Role:** Metadata and enrichment only — diffs, PRs, issues, contributors. Never used for bulk file fetching (see "What NOT to Do"). Driven by C2.

### C4 — Hybrid Parser

The hybrid parser turns a cloned repo on disk (output of C3a) into a durable parse tree. Pass 1 is deterministic and free; Pass 2 is surgical and reasons only about what Pass 1 flagged ambiguous; the indexer persists the result.

#### C4a — Tree-sitter (Pass 1)

**Tech:** py-tree-sitter + grammar `.so` files.

**Role:** Deterministic AST extraction across 25 languages.

- Parses all source files into ASTs
- Extracts nodes: modules, classes, functions, methods
- Extracts EXTRACTED edges: imports, calls (same-file), contains, inherits, decorates
- Flags ambiguous references (unresolved cross-file imports, dynamic calls) for Pass 2
- Supports 25 languages: Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, Ruby, C#, Kotlin, Scala, PHP, Swift, Lua, Zig, Dart, Elixir, Vue, Svelte, and more
- Performance: ~10,000 files/sec

#### C4b — Agent Reasoning (Pass 2)

**Tech:** Agent SDK with grep/glob/read tools.

**Role:** Resolves edges that C4a flagged ambiguous.

- ONLY fires for edges tree-sitter flagged as ambiguous
- Uses glob to find candidate files, grep to locate definitions, read to load specific line ranges
- This surgical tool use loads only 2-3 files per resolution — does NOT pollute the full context
- Resolves: cross-file imports, dynamic dispatch, getattr patterns, decorator-based routing, plugin registries
- Produces INFERRED edges with the resolution reasoning
- For clean codebases: ~10-15% of edges need agent resolution
- For metaprogramming-heavy codebases: ~30-40%

**Key design principle:** The agent's grep/glob/read tool pattern is an active ADVANTAGE over alternatives like LSP. It loads only what's needed (surgical), handles dynamic patterns LSP cannot (flexible), and costs scale with ambiguity not project size (efficient).

#### C4c — Tree Indexer

**Tech:** SQLAlchemy + SQLite.

**Role:** Persists the C4a + C4b parse tree into the `trees` table; PATCH mutates this row in place.

**FULL flow:**
1. After C4a + C4b finish, the resolver returns a `ParseResult` (the parse tree).
2. `index_tree` serializes it (`asdict(parse_result)`) into `trees.tree_data` and inserts a row with status `READY`. Returns `tree_id`.
3. The tree is the durable input for C5a; it survives across requests and lets C5b re-cluster without re-parsing.

**PATCH (incremental update) flow:**
1. `git pull` via subprocess (git protocol — NOT MCP, no API rate limit impact).
2. `git diff last_commit_sha..HEAD --name-status -M` (local git operation).
3. Optionally call C3b (GitHub MCP) `compare_commits` for PR/issue context on changed files (1-2 API calls).
4. Categorize: added, modified, deleted, renamed.
5. Load existing tree from `trees.tree_data`.
6. Re-run C4a on `added ∪ modified` files only (tree-sitter is already file-scoped).
7. Re-run C4b on ambiguous refs that touch changed files only (resolver is already ref-scoped).
8. Mutate the tree:
   - Drop nodes/edges from `deleted ∪ modified` files
   - Add nodes/edges from the re-parse
   - Re-evaluate cross-file edges crossing into changed files
9. Update the `trees` row with the mutated payload and new `last_commit_sha`.
10. C5a rebuilds the `MultiDiGraph` from the mutated tree and UPDATEs `graphs.graph_data` on the existing `graph_id` (status temporarily flips to `BUILDING`).
11. Re-cluster only affected Leiden communities (C5b), UPDATE the same row again to add fresh `community` keys, refresh `community_count`, and flip status back to `READY`.

**Why no separate diff engine:** C4a and C4b are already file/ref-scoped — running them on a smaller input is the easy part. The non-trivial logic is the tree mutation, which lives in the PATCH flow (dispatcher / tree mutator) right next to where it's called. A standalone "diff engine" component would have been ceremony around `len()` calls in FULL mode and a thin wrapper in PATCH; it was removed.

### C5 — Graph Engine

#### C5a — Graph Builder

**Tech:** NetworkX.

**Role:** Merges EXTRACTED + INFERRED edges from the parse tree into a unified graph.

- Entry point: `build_graph(tree_id) -> GraphBuildResult` in `graph_engine/networkX_graph_builder/`.
- Loads the parse tree from `trees.tree_data` via `graph_engine/utils/db_utils.py`. The query is scoped on `(tree_id, status = READY)` — non-ready trees are invisible at the SQL layer, never fetched-then-rejected.
- Produces a `networkx.MultiDiGraph`: directed (preserves CALLS/IMPORTS direction) and multi-edge (a module can both `IMPORTS` and `CALLS` into another and both survive into the graph).
- Edge endpoints not present in `tree.nodes` (cross-repo imports, module-level globals tree-sitter doesn't extract as nodes) get a synthetic `type = "external"` node so the graph is structurally complete and no signal is lost before C5b.
- `g.graph` carries repo-level metadata: `repo`, `root`, `tree_id`, `graph_id`, `last_commit_sha`. Every edge carries `type`, `confidence`, `weight`, `metadata`.
- Edges with an unknown `type` are dropped and counted in `edges_dropped` (logged, not raised) so a corrupted tree never silently produces a malformed graph.
- The orchestrator immediately persists the build result via `persist_graph` in `graph_engine/utils/db_utils.py` — UPSERT into `graphs` (keyed on `(user_id, repo_url, branch)`) with `graph_data = {nodes, edges}`, `status = 'BUILDING'`, `community_count = 0`. The `graph_id` is returned to the client even before C5b runs, so the row is inspectable mid-pipeline.

**Node schema (within `graph_data` JSON):**
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
  "community": 3,
  "is_god": false,
  "is_orphan": false
}
```
Node types: `module`, `class`, `function`, `method`, `external` (synthetic, for cross-repo endpoints).

**Edge schema (within `graph_data` JSON):**
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
Edge types: `IMPORTS`, `CALLS`, `CONTAINS`, `INHERITS`, `DECORATES`, `RELATES_TO`, `DEPENDS_ON`.
Confidence levels: `EXTRACTED` (tree-sitter, high trust), `INFERRED` (agent, medium trust).

#### C5b — Leiden Clustering

**Tech:** graspologic (Microsoft).

**Role:** Community detection on graph topology — no embeddings.

- Entry point: `cluster_graph(graph_id) -> ClusterResult` in `graph_engine/leiden_clustering/`.
- Loads the C5a-built graph from `graphs.graph_data` (via `load_graph`), projects the `MultiDiGraph` to an undirected weighted simple graph (parallel + reverse edges summed), runs Leiden, writes `community` / `is_god` / `is_orphan` onto each node, and UPDATEs the same `graphs` row in place — flipping `status` to `READY` and setting `community_count`.
- Resolution parameter: 1.0 (tune per repo size).
- Quality function: modularity (CPM for very large repos).
- Iterations: until convergence (typically 2-4).
- Post-clustering: `is_god` flag for nodes whose neighbours span 2+ communities other than their own (utility / registry / dispatcher hubs); `is_orphan` flag for isolates (dead-code candidates).
- Lazy-imports `graspologic` (which transitively pulls umap/pynndescent/numba, ~4s import time) so FastAPI cold start stays under a second.

### C6 — QnA Agent

**Tech:** `ClaudeSDKClient`. **Status:** not yet built.

**Role:** Answers questions grounded in a graph subgraph.

**Flow:**
1. User asks a question.
2. Load `graph_data` from C8 by `graph_id`.
3. BFS from nodes matching the query keywords — extract 2-hop neighborhood subgraph.
4. Serialize subgraph as context (~2k tokens, NOT the full repo).
5. Send to `ClaudeSDKClient` with system prompt enforcing graph-grounded answers.
6. Return answer with references to specific graph nodes and files.

**Why `ClaudeSDKClient` and NOT Agent SDK for QnA:**
- QnA does not need tools (no grep/read/glob) — the graph IS the context.
- Single completion call, no tool loop — lower latency.
- Lower cost: one API call, not multiple agent steps.

### C7 — React Frontend

**Tech:** React + react-force-graph (WebGL). **Status:** not yet built.

**Role:** Interactive graph visualization with semantic zoom.

**Features:**
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

### C8 — Persistence

**Tech:** SQLite (`meridian.db`).

**Role:** Durable persistence for everything Meridian must remember across requests, container restarts, and cache eviction. Shared by every other component.

Five tables: `users`, `graphs`, `trees`, `repo_clones`, `sync_runs`. See **Database Schema** below for column-level detail.

## Request Flow

Every `/repos` request is dispatched the same way: C1 is a thin validator that delegates to C2; C2 is the only component that decides what to run, in what order, and against which primitives. C3, C4, C5, and C6 are leaves — they take a typed input, do one job, and return.

**FULL build (no active graph for `repo_url + branch`):**
```
Client
  ↓
API Gateway (C1, FastAPI)                          ← validates request, no business logic
  ↓
Orchestrator (C2, orchestrator/orchestrator.py)
  │   has_active_graph(repo_url, branch) → False   ← read from C8
  ↓
  ├─→ Git Client (C3a, subprocess clone)           ← write into /var/meridian/cache/
  │     and persist_clone() row in repo_clones
  ↓
  ├─→ Tree-sitter (C4a)                            ← parse all source files → ParseResult
  ↓
  ├─→ Agent Reasoning (C4b)                        ← resolve ambiguous refs → INFERRED edges
  ↓
  ├─→ Tree Indexer (C4c)                           ← persist parse tree to `trees` → tree_id
  ↓
  ├─→ Graph Builder (C5a) → C8                     ← build MultiDiGraph, UPSERT graphs row with
  │                                                   unclustered graph_data, status='BUILDING'
  │                                                   → returns graph_id (returned to client even
  │                                                   before clustering finishes)
  ↓
  ├─→ Leiden Clustering (C5b) → C8                 ← UPDATE the same graphs row in place: add
  │                                                   `community` / `is_god` / `is_orphan` to each
  │                                                   node, flip status='READY', set community_count
  ↓
  ├─→ link_tree_to_graph (C2 → C8)                 ← drop any stale tree on this graph_id, set
  │                                                   trees.graph_id on the new tree
  ↓
  └─→ record_sync_run (C2 → C8)                    ← audit row, mode='FULL', status='SUCCESS'
```

**PATCH update (active graph already exists):**
```
Client
  ↓
API Gateway (C1)
  ↓
Orchestrator (C2)
  │   has_active_graph(repo_url, branch) → True    ← FULL/PATCH decision
  ↓
  ├─→ Git Client (C3a, subprocess pull)            ← refresh existing clone in /var/meridian/cache/
  ↓
  ├─→ GitHub MCP (C3b)                             ← compare_commits for PR/issue context (1–2 API calls)
  ↓
  ├─→ Tree-sitter (C4a, file-scoped)               ← re-parse changed files only
  ↓
  ├─→ Agent Reasoning (C4b, ref-scoped)            ← re-resolve refs touching changed files
  ↓
  ├─→ Tree Indexer (C4c, mutate)                   ← drop/add nodes/edges in stored tree,
  │                                                   update last_commit_sha
  ↓
  ├─→ Graph Builder (C5a) → C8                     ← rebuild MultiDiGraph from mutated tree,
  │                                                   UPDATE graph_data on existing graph_id
  │                                                   (status flips back to 'BUILDING' for the
  │                                                   duration of the re-cluster)
  ↓
  ├─→ Leiden Clustering (C5b, partial) → C8        ← re-cluster only affected communities,
  │                                                   UPDATE graph_data + community_count,
  │                                                   flip status='READY'
  ↓
  └─→ record_sync_run (C2 → C8)                    ← audit row, mode='PATCH', status='SUCCESS'
```

**QnA (`POST /repos/{graph_id}/query`):**
```
Client
  ↓
API Gateway (C1)
  ↓
Orchestrator (C2)
  │   load graph_data from C8 by graph_id
  │   BFS 2-hop subgraph from query keywords (~2k tokens)
  ↓
  └─→ QnA Agent (C6, ClaudeSDKClient)              ← single completion, no tools → answer
```

**Component ownership in one line:**
- **C1 (API Gateway)** — HTTP boundary. Validates, delegates to C2. Owns no business logic.
- **C2 (Orchestrator)** — every routing decision. Reads `has_active_graph` and writes audit rows from `orchestrator/utils/db_utils.py`. Calls into C3 / C4 / C5 / C6.
- **C3 (Ingestion)** — pure side effects on disk and remote APIs. Only DB writes are clone-side (`persist_clone` in `ingestion_layer/utils/db_utils.py`). Never decides *whether* to run; C2 does.
- **C4 / C5 / C6** — each takes a typed input, does one job, returns. None of them know about HTTP, the FULL/PATCH split, or each other's existence. C2 wires them together.
- **C8 (Persistence)** — passive. Every other component reads/writes through SQLAlchemy via `db/database.py::get_session()`. There is no service in front of it.

## Database Schema

C8 stores everything Meridian must remember. Five tables: `users`, `graphs`, `trees`, `repo_clones`, `sync_runs`.

**Users table:**
```sql
CREATE TABLE users (
    user_id         TEXT PRIMARY KEY,   -- UUID
    email           TEXT UNIQUE NOT NULL,
    display_name    TEXT NOT NULL,
    github_username TEXT,
    password        TEXT NOT NULL,      -- bcrypt or argon2 hash, NEVER plaintext
    role            TEXT DEFAULT 'member', -- 'admin' | 'member'
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at   TIMESTAMP
);
```

**Graphs table:**
```sql
CREATE TABLE graphs (
    graph_id        TEXT PRIMARY KEY,   -- UUID
    user_id         TEXT NOT NULL,      -- FK → users.user_id
    repo_clone_id   TEXT,               -- FK → repo_clones.repo_id (ON DELETE SET NULL)
    repo_url        TEXT NOT NULL,
    branch          TEXT DEFAULT 'main',
    last_commit_sha TEXT,
    graph_data      TEXT,               -- JSON: {nodes, edges}. C5a writes the unclustered graph
                                        -- on FULL build (status='BUILDING'); C5b mutates the
                                        -- same row in place, adding `community` / `is_god` /
                                        -- `is_orphan` to each node and flipping status='READY'.
    status          TEXT DEFAULT 'BUILDING', -- 'BUILDING' | 'READY' | 'ERROR'
    node_count      INTEGER DEFAULT 0,
    edge_count      INTEGER DEFAULT 0,
    community_count INTEGER DEFAULT 0,
    error_message   TEXT,               -- populated when status = 'ERROR'
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_synced_at  TIMESTAMP,
    UNIQUE (user_id, repo_url, branch), -- C5a's upsert conflict target
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

**Trees table:** parse-tree artifact (C4a + C4b output, persisted by C4c). One tree per graph; FULL inserts, PATCH mutates in place.
```sql
CREATE TABLE trees (
    tree_id          TEXT PRIMARY KEY,   -- UUID
    graph_id         TEXT UNIQUE,        -- FK → graphs.graph_id (ON DELETE CASCADE)
    tree_data        TEXT,               -- JSON: {repo, root, files_parsed, files_skipped,
                                         --        languages, errors, nodes, edges, ambiguous}
    last_commit_sha  TEXT,
    status           TEXT DEFAULT 'BUILDING', -- 'BUILDING' | 'READY' | 'ERROR'
    node_count       INTEGER DEFAULT 0,
    edge_count       INTEGER DEFAULT 0,
    ambiguous_count  INTEGER DEFAULT 0,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Repo clones table:** per-user on-disk clone metadata. Rows are kept as tombstones after eviction so `last_commit_sha` survives cache deletion (re-clone can resume from that SHA).
```sql
CREATE TABLE repo_clones (
    repo_id          TEXT PRIMARY KEY,   -- deterministic hash of repo_url
    user_id          TEXT,               -- FK → users.user_id (ON DELETE CASCADE)
    owner            TEXT NOT NULL,
    repo             TEXT NOT NULL,
    repo_url         TEXT NOT NULL,
    branch           TEXT,
    path             TEXT NOT NULL,      -- on-disk cache path
    last_commit_sha  TEXT,
    size_bytes       BIGINT,
    cloned_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    evicted_at       TIMESTAMP,          -- set when cache dir is deleted; cleared on re-clone
    UNIQUE (user_id, owner, repo, branch)
);
```

**Sync runs table:** audit row for one build (FULL) or incremental sync (PATCH). Backs build history and the `WS /repos/{graph_id}/status` channel; the single-slot `graphs.error_message` only carries the latest.
```sql
CREATE TABLE sync_runs (
    run_id            TEXT PRIMARY KEY,   -- UUID
    graph_id          TEXT NOT NULL,      -- FK → graphs.graph_id (ON DELETE CASCADE)
    mode              TEXT NOT NULL,      -- 'FULL' | 'PATCH'
    status            TEXT DEFAULT 'RUNNING', -- 'RUNNING' | 'SUCCESS' | 'ERROR'
    previous_sha      TEXT,
    current_sha       TEXT,
    nodes_added       INTEGER DEFAULT 0,
    nodes_removed     INTEGER DEFAULT 0,
    edges_added       INTEGER DEFAULT 0,
    edges_removed     INTEGER DEFAULT 0,
    ambiguous_added   INTEGER DEFAULT 0,
    ambiguous_removed INTEGER DEFAULT 0,
    error_message     TEXT,
    started_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at       TIMESTAMP
);
```

**Key rules:**
- `graph_id` is returned to the user on `POST /repos`. All subsequent operations use this ID.
- Graphs persist until an explicit `DELETE /repos/{graph_id}` is called. No TTL, no auto-eviction. Cascade deletes the tree and sync_runs rows.
- Users can only access graphs where `user_id` matches their authenticated identity.
- `node_count` and `edge_count` on `graphs` are populated by C5a at upsert time and reflect the unclustered graph. `community_count` is set by C5b when it mutates the row (0 while status is `BUILDING`). The denormalization on `trees` (`node_count`, `edge_count`, `ambiguous_count`) reflects the parse tree (post-C4b).
- `graphs.status` tracks the build lifecycle: `BUILDING` (set by C5a upsert) → `READY` (set by C5b UPDATE in place), or `BUILDING` → `ERROR`. `graph_data` is non-null as soon as C5a finishes — clients can fetch the unclustered graph by `graph_id` immediately, and the row is mutated (not replaced) once C5b runs.
- `trees.status` tracks the parse-tree lifecycle independently: `BUILDING` during C4a/C4b, `READY` after C4c commits.

**Relationships:**
- One user owns many graphs and many repo_clones.
- One graph has exactly one tree (1:1 via `trees.graph_id UNIQUE`) and many sync_runs (1:N).
- One repo_clone may back many graphs over time (e.g. across re-builds), but at any moment a graph points at one clone via `graphs.repo_clone_id`.

## Storage Model

Meridian separates ephemeral storage (cheap, evictable) from durable storage (persists until explicit delete).

**Ephemeral — Repo cache (filesystem artifact of C3a):**
- Location: `/var/meridian/cache/{repo_hash}/`
- Contains: git clones (`.git/` + source files)
- Lifecycle: auto-evicted by TTL (7 days idle) or LRU (disk budget exceeded)
- Size: ~100MB-2GB per clone
- Loss impact: zero — re-clone on next sync, graph already safe in C8

**Durable — SQLite database (C8):**
- Location: `/var/meridian/db/meridian.db`
- Contains: `users`, `graphs` (clustered output JSON), `trees` (parse tree JSON), `repo_clones` (clone metadata + tombstones), `sync_runs` (build history)
- Lifecycle: persists until explicit DELETE call, survives cache eviction / container restarts
- Size: ~1-5MB per graph record (`graph_data`) + ~1-3MB per tree (`tree_data`) for medium repos
- Loss impact: catastrophic — this IS the product. Back up this file.

**Re-clone scenario:** When a user syncs a graph whose cache has been evicted, Meridian reads `last_commit_sha` from the surviving `repo_clones` tombstone (or `graphs` row), re-clones the repo to cache, runs `git diff` from that SHA, loads the existing tree from `trees.tree_data`, mutates it for the changed files, re-clusters, writes the updated graph back to C8, and optionally evicts the cache again.

## Deployment

Single Docker image with SQLite for persistence.

**Container contents:**
- FastAPI server (C1 + static React SPA serving)
- git CLI (C3a — for clone/pull via git protocol, no API rate limit impact)
- py-tree-sitter + 25 language grammar `.so` files (C4a)
- Agent SDK runtime (C2 + C4b)
- ClaudeSDKClient runtime (C6)
- NetworkX + graspologic (C5)
- SQLite (C8 — embedded, no separate server process)

**Volume mount:** `/var/meridian/` — contains both `db/meridian.db` and `cache/` directory.

```yaml
# docker-compose.yml
volumes:
  - ./meridian-data:/var/meridian
```

```
./meridian-data/              ← on host machine
├── db/
│   └── meridian.db           ← durable: users + graphs (back this up)
└── cache/                    ← ephemeral: git clones (evictable)
    ├── a1b2c3d4/
    └── e5f6g7h8/
```

**External dependencies (network):**
- GitHub (git protocol) — for initial clone and pull operations (NOT rate limited)
- GitHub REST API (via C3b MCP server) — for metadata enrichment only: diffs, PRs, issues, contributors (rate limited: 5,000/hr per PAT)
- Anthropic API — for Agent SDK (C2 orchestration + C4b Pass 2) and ClaudeSDKClient (C6 QnA)

**Repo cache lifecycle:**
- Created on first `POST /repos` (git clone into cache)
- Updated via `git pull` on `POST /repos/{graph_id}/sync`
- Evicted after configurable TTL (default: 7 days idle)
- Disk budget per instance (default: 50GB), LRU eviction when full
- Eviction deletes ONLY the cache directory — the graph in C8 is untouched

## Authentication

Meridian uses JWT-based authentication.

**Flow:**
1. `POST /auth/register` — create account with email, display_name, password
2. `POST /auth/login` — returns a JWT token (short-lived, e.g. 24h expiry)
3. All `/repos` endpoints require `Authorization: Bearer <token>` header
4. Token contains `user_id` — used to scope all DB queries to that user's graphs

**Password handling:**
- Hash with bcrypt or argon2 before storing in `users.password` (the column holds a hash, not plaintext, despite the column name)
- NEVER store plaintext passwords
- NEVER log passwords or tokens

**Authorization rules:**
- Users can only list, view, query, sync, and delete their own graphs
- `DELETE /repos/{graph_id}` verifies `graph.user_id == authenticated_user.user_id`
- Admin role can access all graphs (future use)

## Key Design Decisions

1. **No LSP** — We explicitly chose NOT to use Language Server Protocol. The Agent SDK's grep/glob/read tools (C4b) provide surgical cross-file resolution that handles dynamic patterns LSP cannot, loads only needed context, and requires no language-server infrastructure.

2. **Tree-sitter over Python ast** — Tree-sitter (C4a) supports 25 languages vs Python ast's Python-only limitation. This makes Meridian a general-purpose tool, not a Python-only niche.

3. **Hybrid ingestion: git clone + GitHub MCP** — Initial bulk fetch uses `git clone` via subprocess (C3a, git protocol, zero API calls). GitHub MCP (C3b) is used ONLY for metadata enrichment (PRs, issues, contributors, diff context) — NOT for file content fetching. This avoids GitHub's 5,000 requests/hour rate limit, which the MCP's per-file `get_file_contents` would exhaust on a single medium-sized repo.

4. **Agent SDK for orchestration, ClaudeSDKClient for QnA** — Different tools for different jobs. C2 orchestration needs tool use; C6 QnA needs single-shot completion with graph context.

5. **SQLite for durable persistence, filesystem for ephemeral cache** — Graphs and users live in C8 (`meridian.db`), keyed by UUID, persisting until explicit delete. Git clones live in the cache directory and are auto-evicted. This separates the valuable (graphs) from the disposable (clones).

6. **Differential updates from day one** — Not an afterthought. The persisted parse tree (`trees` table) plus tree-mutation in the PATCH flow is how incrementality is achieved. There is no standalone "diff engine" — C4a/C4b are already file/ref-scoped, so PATCH just calls them on a smaller input and C4c mutates the stored tree in place.

7. **Two confidence tiers** — Every edge is tagged EXTRACTED (C4a tree-sitter, deterministic) or INFERRED (C4b agent, probabilistic). This transparency is surfaced in both the C6 QnA answers and the C7 frontend visualization.

8. **Never use GitHub MCP for bulk file fetching** — Each MCP `get_file_contents` call = 1 REST API request. A 500-file repo = 500 API calls. With a 5,000/hour shared rate limit, this is catastrophic for multi-repo or multi-user scenarios. `git clone` via subprocess (C3a) is the only correct approach for initial builds.

9. **Every graph is owned by a user** — The `graphs.user_id` FK ensures every graph is scoped to the user who triggered the build. No anonymous builds, no shared graphs (unless explicitly added later).

10. **Persistence is its own component, not a leaf of any layer** — C8 is shared by every other component. Treating it as a sub-unit of the graph engine would mis-state ownership; promoting it to a top-level component makes the cross-cutting nature explicit.

## Cost Model

| Component | Cost |
|-----------|------|
| C3a Git Client (clone/pull) | Free — git protocol, no API rate limit |
| C3b GitHub MCP (metadata) | API rate limit — 5-20 calls per sync (well within 5,000/hr budget) |
| C4a Tree-sitter (Pass 1) | Free — local, deterministic |
| C4b Agent SDK (Pass 2) | Token cost — per ambiguous edge resolution |
| C4c Tree Indexer | Free — local SQLite write |
| C5a Graph Builder | Free — local CPU |
| C5b Leiden Clustering | Free — local CPU |
| C2 Agent SDK (orchestration) | Token cost — pipeline coordination |
| C6 ClaudeSDKClient (QnA) | Token cost — per user query |
| C8 SQLite (persistence) | Free — embedded, no server process |
| Server compute | Infrastructure cost — Docker container |
| Disk storage | Infrastructure cost — DB file + cache directory |

**Optimization principle:** Tree-sitter (C4a) handles ~80% of edges for free. Agent tokens (C4b) only burn on the ~20% that genuinely need reasoning. On incremental updates, only changed-file edges incur agent cost.

## Security Considerations

- Passwords are hashed with bcrypt or argon2 — NEVER stored as plaintext
- JWT tokens are short-lived (24h) and must be validated on every request
- GitHub PATs must be handled carefully — minimum required scopes (`repo` for private, none for public), never logged, never stored beyond the session
- PATs are used for both git clone authentication AND GitHub MCP API calls — same token, different protocols
- Users can only access their own graphs — every DB query is scoped by `user_id` from the JWT
- Private repo code is cloned to server disk — ensure proper isolation between users via separate cache directories
- Repo clones are ephemeral and auto-evicted — minimize exposure window for sensitive code
- `meridian.db` (C8) contains user credentials (hashed) and all graph data — protect this file, back it up, restrict filesystem access
- No telemetry, no usage tracking, no analytics
- Outbound network calls are limited to: GitHub (git protocol for clone/pull), GitHub REST API (via C3b for metadata only), and Anthropic API (Agent SDK + ClaudeSDKClient)
- The git clone subprocess must sanitize the repo URL to prevent command injection (never pass unsanitized user input to shell commands)

## Commands Reference

When building Meridian, use these as the target CLI / API commands:

```bash
# Authentication
POST /auth/register            # Create user account
POST /auth/login               # Get JWT token

# Graph operations (all require JWT)
POST /repos                    # Submit repo for graph building
GET  /repos                    # List user's graphs
GET  /repos/{graph_id}/graph   # Get the knowledge graph
POST /repos/{graph_id}/query   # Ask a question
POST /repos/{graph_id}/sync    # Trigger incremental update
DELETE /repos/{graph_id}       # Permanently delete a graph
WS   /repos/{graph_id}/status  # Stream build progress
```

## What NOT to Do

- Do NOT use GitHub MCP's `get_file_contents` for bulk file fetching — this burns 1 API call per file and will exhaust the 5,000/hr rate limit on any non-trivial repo. Use `git clone` via subprocess (C3a) instead.
- Do NOT use GitHub MCP for `git pull` — use subprocess directly. The git protocol is not rate limited; the REST API is.
- Do NOT use LSP or language servers — we explicitly decided against this.
- Do NOT use Python's built-in `ast` module — tree-sitter (C4a) replaces it for multi-language support.
- Do NOT use the Anthropic API directly — use Claude Code Agent SDK for orchestration (C2) and Pass 2 (C4b), and ClaudeSDKClient for QnA (C6).
- Do NOT store `graph.json` on the filesystem — all graph data goes into C8, keyed by `graph_id`.
- Do NOT auto-delete graphs — graphs persist until the user explicitly calls DELETE.
- Do NOT allow users to access other users' graphs — every query must be scoped by `user_id` from JWT.
- Do NOT store plaintext passwords — always hash with bcrypt or argon2.
- Do NOT send full repo contents to the LLM — always use surgical grep/glob/read tool calls.
- Do NOT rebuild the full graph on sync when an active graph already exists — load the existing `trees.tree_data`, mutate it for changed files, and re-cluster only affected communities.
- Do NOT make the frontend a separate deployment — it ships as a static build served by C1.
- Do NOT pass unsanitized user-provided repo URLs to subprocess shell commands — always validate and sanitize to prevent command injection.
- Do NOT treat the cache directory as durable storage — it is ephemeral and evictable. C8 is the source of truth.
