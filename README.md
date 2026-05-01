# Meridian

> A remote-first, agent-powered code knowledge graph builder.

Point Meridian at any GitHub repository and get back an interactive, queryable knowledge graph — no local install required. Built with the Claude Code Agent SDK, tree-sitter, NetworkX, and Leiden clustering.

## Features

- **Zero install for end users** — just provide a GitHub URL (and a PAT for private repos).
- **Three-pass parsing** — tree-sitter (Pass 1) for deterministic AST extraction across 25 languages, a symbol-index workload reducer (Pass 1.5) that resolves the easy cross-file refs without an LLM call, and agent reasoning (Pass 2) for surgical resolution of what's left.
- **Differential updates** — incremental graph patches in seconds via a built-in diff engine; no full rebuilds.
- **Graph-grounded QnA** — multi-turn streaming chat with answers that cite specific nodes and files, not hallucinated references.
- **Interactive visualization** — 3D WebGL-rendered force graph with semantic zoom, community coloring, and confidence-weighted edges.
- **Rate-limit-safe ingestion** — bulk file fetching uses `git clone` via subprocess (git protocol, zero API calls); GitHub MCP is used only for metadata enrichment.

---

## Architecture

Meridian is structured as **eight top-level components** (C1–C8) with sub-units lettered (e.g. C3a, C4b). C8 is shared persistence — every other component reads or writes through it.

```mermaid
flowchart TD
    C1["<b>C1 — API gateway</b>"]
    C2["<b>C2 — Orchestrator</b><br/>Agent SDK · FULL vs PATCH"]

    C3["<b>C3 — Ingestion</b><br/>Clone + MCP"]
    C3a["C3a Git CLI"]
    C3b["C3b MCP"]

    C4["<b>C4 — Hybrid parser</b><br/>Tree-sitter + Reducer + Agent"]
    C4a["C4a TS"]
    C4ab["C4ab Reducer"]
    C4b["C4b Agent"]
    C4c["C4c Index"]

    C5["<b>C5 — Graph engine</b><br/>NetworkX + Leiden"]
    C5a["C5a Build"]
    C5b["C5b Cl."]

    C6["<b>C6 — QnA agent</b><br/>ClaudeSDKClient"]
    C7["<b>C7 — React frontend</b><br/>WebGL force-graph"]
    C8["<b>C8 — SQLite persistence</b>"]

    C1 --> C2
    C2 --> C3
    C2 --> C4
    C2 --> C5
    C2 --> C6

    C3 --> C3a
    C3 --> C3b

    C4 --> C4a
    C4 --> C4ab
    C4 --> C4b
    C4 --> C4c

    C5 --> C5a
    C5 --> C5b

    C3a -.-> C8
    C4c -.-> C8
    C5a -.-> C8
    C5b -.-> C8
    C6  -.-> C8
    C7  -.-> C8

    classDef gateway     fill:#1e3a5f,color:#fff,stroke:none
    classDef orchestrate fill:#4c3a8a,color:#fff,stroke:none
    classDef ingestion   fill:#1f5a48,color:#fff,stroke:none
    classDef parser      fill:#5a3a2c,color:#fff,stroke:none
    classDef engine      fill:#6b5418,color:#fff,stroke:none
    classDef output      fill:#6a3a4a,color:#fff,stroke:none
    classDef persistence fill:#3a3a3a,color:#fff,stroke:none

    class C1 gateway
    class C2 orchestrate
    class C3,C3a,C3b ingestion
    class C4,C4a,C4ab,C4b,C4c parser
    class C5,C5a,C5b engine
    class C6,C7 output
    class C8 persistence
```

_Solid arrows = synchronous calls. Dashed arrows = persistence reads/writes; every component touches C8._

### Layer 1 — Ingestion

| Component | Technology | Role |
| ----------- | ---------- | ------ |
| C1: API Gateway | FastAPI | REST endpoints, WebSocket QnA, serves React SPA |
| C3a: Git Client | git CLI (subprocess) | Initial clone + pull via git protocol — zero API rate limit impact. Writes ephemeral clones to `ingestion_layer/repo_cache/codebase/<repo>/` (override via `CACHE_ROOT`) |
| C3b: GitHub MCP | GitHub MCP Server | Metadata only: commits between SHAs, PRs, issues |

**Hybrid ingestion model (rate-limit protection):**

| Operation | Method | API calls |
| ----------- | -------- | ----------- |
| Initial build | `git clone` via subprocess | 0 |
| Incremental update | `git pull` via subprocess + MCP diff | 2–5 |
| Metadata enrichment | GitHub MCP (PRs, issues, contributors) | 5–20 |
| **Total per sync** | | **~10–25** (vs 500–2000+ with MCP-only) |

### Layer 2 — Processing

| Component | Technology | Role |
| ----------- | ---------- | ------ |
| C2: Orchestrator | Plain async Python + Agent SDK (inside C4b) | Coordinates pipeline; makes FULL vs PATCH decisions |
| C4a: Tree-sitter (Pass 1) | `tree-sitter-language-pack` | Deterministic AST extraction across 25 languages → `EXTRACTED` edges |
| C4ab: Workload Reducer (Pass 1.5) | Symbol-index reducer (no LLM) | Resolves easy cross-file refs via project-wide symbol index → `EXTRACTED` edges |
| C4b: Agent Reasoning (Pass 2) | Agent SDK tools | Resolves ambiguous edges with grep/glob/read → `INFERRED` edges |
| C4c: Tree Indexer | SQLAlchemy + SQLite | Persists the C4a+C4ab+C4b parse tree to `trees`; mutated in place during PATCH |

**Pass 1** extracts modules, classes, functions, methods, and all deterministic edges (imports, same-file calls, contains, inherits, decorates) from raw ASTs. Cross-file / dynamic refs are flagged as `AmbiguousRef`.

**Pass 1.5** routes each `AmbiguousRef` through a language-specific reducer that builds a project-wide symbol index. Typical mixed-repo split: ~88% dropped (external/stdlib, no project match), ~10% resolved (unique cross-file matches), ~2% passed through to Pass 2.

**Pass 2** fires only when refs survive Pass 1.5. It uses `glob` to find candidate files, `grep` to locate definitions, and `read` to load specific line ranges — loading 2–3 files per resolution rather than the full repo.

### Layer 3 — Graph

| Component | Technology | Role |
| ----------- | ---------- | ------ |
| C5a: Graph Builder | NetworkX (`MultiDiGraph`) | Merges `EXTRACTED` + `INFERRED` edges; synthesises external nodes for cross-repo endpoints |
| C5b: Leiden Clustering | graspologic | Community detection on graph topology; no embeddings. Flags `is_god` (cross-community hubs) and `is_orphan` (isolates) |
| C8: Graph Store | SQLite (`db/meridian.db`) | Six tables: `users`, `graphs`, `trees`, `repo_clones`, `sync_runs`, `graph_history` |

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
  "community": 3,
  "is_god": false,
  "is_orphan": false
}
```

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
Confidence levels: `EXTRACTED` (tree-sitter, high trust) · `INFERRED` (agent, medium trust)

### Layer 4 — Output

| Component | Technology | Role |
| ----------- | ---------- | ------ |
| C6: QnA Agent | ClaudeSDKClient (multi-turn streaming) | Multi-turn WebSocket chat grounded in graph context |
| C7: React Frontend | React 18 + Vite + `react-force-graph-3d` (3D WebGL) + Zustand + Tailwind | Interactive 3D graph visualization with semantic zoom |

**QnA flow:** Per turn, server-side retrieval composes three tools — `search_nodes` (keyword-score top-K seeds), `get_neighbours` (full inbound/outbound edges per seed), `get_community` (Leiden cluster members) — formats them as readable text, and injects as `<graph_context>` into a streaming `ClaudeSDKClient` session. Session is reused across turns over a single WebSocket so prior history stays in the model's context.

**Frontend:** 3D force-directed WebGL layout (`react-force-graph-3d`, handles 5k+ nodes), Leiden community coloring, confidence-weighted edge thickness, partial semantic zoom, node sidebar with file link, multi-turn QnA playground (`PlaygroundChat`) over `WS /playground/{graph_id}`.

---

## API Reference

All `/repos` and `/graph` endpoints require `Authorization: Bearer <token>`. The PAT is passed per-request via the `X-GitHub-PAT` header on `/repos/sync` and is never stored.

| Method | Path | Description |
| -------- | ------ | ------------- |
| `POST` | `/auth/register` | Create a user account |
| `POST` | `/auth/login` | Authenticate; returns 24h JWT |
| `POST` | `/repos/sync` | Single dispatch — orchestrator picks FULL vs PATCH internally |
| `GET` | `/repos` | List authenticated user's graphs (metadata only) |
| `GET` | `/graph?graph_id=...` | Fetch the full knowledge graph JSON (nodes + edges) |
| `DELETE` | `/repos/{graph_id}` | Permanently delete a graph (cascades tree, history, clone) |
| `WS` | `/playground/{graph_id}?token=<JWT>&query=<initial>&agentic=<bool>` | Multi-turn streaming QnA |
| `WS` | `/repos/{graph_id}/status` | Stream build progress (TODO — not yet wired) |

---

## Database Schema

Six tables — `users`, `graphs`, `trees`, `repo_clones`, `sync_runs`, `graph_history`. SQLAlchemy entities live in `db/entities/`; engine + session lifecycle in `db/database.py` (PRAGMA `foreign_keys=ON` on every connection).

| Table | Purpose | Key columns |
| ------- | --------- | ------------- |
| `users` | Account records | `user_id` (PK), `email` UNIQUE, bcrypt `password`, `role` |
| `graphs` | Live graph payload (mutated in place across syncs) | `graph_id` (PK), `user_id` FK, `repo_clone_id` FK, `repo_url`, `branch`, `graph_data` JSON, `status` (`BUILDING`/`READY`/`ERROR`), counts. UNIQUE `(user_id, repo_url, branch)` |
| `trees` | Durable parse tree from C4 (mutated in place during PATCH) | `tree_id` (PK), `graph_id` FK UNIQUE, `tree_data` JSON, `last_commit_sha`, `status` |
| `repo_clones` | Clone tombstones — keep `last_commit_sha` after eviction so re-clone can resume | `repo_id` (PK, hash of repo_url), `user_id` FK, `path`, `evicted_at`. UNIQUE `(user_id, owner, repo, branch)` |
| `sync_runs` | Per-build audit row | `run_id` (PK), `graph_id` FK, `mode` (`FULL`/`PATCH`), `status`, delta counts, timestamps |
| `graph_history` | Immutable per-version snapshots of `graph_data` | `history_id` (PK), `graph_id` FK, `version` (monotonic), `run_id` FK, `graph_data` snapshot. UNIQUE `(graph_id, version)` |

`DELETE /repos/{graph_id}` cascades the tree, history, and clone record (and rmtrees the cache directory) but intentionally leaves `sync_runs` rows orphaned as a historical audit trail.

---

## Storage Model

| Storage | Location | Lifecycle | Loss impact |
| --------- | ---------- | ----------- | ------------- |
| Repo cache (ephemeral) | `ingestion_layer/repo_cache/codebase/<repo>/` (override via `CACHE_ROOT`) | TTL + LRU disk-budget eviction (TODO) | Zero — re-clone on next sync |
| SQLite DB (durable) | `db/meridian.db` | Persists until explicit `DELETE /repos/{graph_id}` | Catastrophic — back this up |

---

## Deployment

Single Docker image. FastAPI serves both the API and the built React SPA from `api/static/`. SQLite is embedded (no separate DB server).

**Container contents:** FastAPI + uvicorn (C1, serves static SPA), git CLI (C3a), `tree-sitter-language-pack` (C4a), Agent SDK runtime (C4b), NetworkX + graspologic (C5), SQLite (C8).

**External network dependencies:**
- GitHub (git protocol) — clone + pull, not rate limited
- GitHub REST API via MCP — metadata enrichment only, ≤20 calls per sync
- Anthropic API (or AWS Bedrock when `CLAUDE_CODE_USE_BEDROCK=1`) — Agent SDK (Pass 2) + ClaudeSDKClient (QnA)

---

## Cost Model

| Component | Cost |
| ----------- | ------ |
| git clone / pull | Free — git protocol |
| Tree-sitter Pass 1 | Free — local, deterministic |
| Workload reducer Pass 1.5 | Free — local symbol-index resolution |
| Diff engine | Free — local git operations |
| Graph builder + Leiden | Free — local CPU |
| SQLite persistence | Free — embedded |
| GitHub MCP metadata | ≤20 API calls per sync (within 5,000/hr budget) |
| Agent SDK Pass 2 | Token cost — per ambiguous edge that survives Pass 1.5 |
| ClaudeSDKClient QnA | Token cost — per user turn (graph context injected server-side) |

**Optimization principle:** Pass 1 (tree-sitter) and Pass 1.5 (reducer) together resolve the vast majority of edges for free — the reducer alone drops ~88% of ambiguous refs and resolves another ~10% via deterministic symbol matching. Agent tokens burn only on the ~2% that genuinely need reasoning. On incremental syncs, only changed-file edges incur agent cost.

---

## Status

Early-stage. Proprietary — All Rights Reserved. See [LICENSE](LICENSE).

---

**Author:** Arka Patra
