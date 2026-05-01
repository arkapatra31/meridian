# CLAUDE.md — Meridian

## What is Meridian?

Meridian is a remote-first, agent-powered code knowledge graph builder. A user points it at any GitHub repository URL and gets back an interactive, queryable knowledge graph — no local installation required on the user's end.

Meridian is proprietary software. All rights reserved. No part of this codebase may be reproduced, distributed, or used without explicit written consent.

## Core Value Proposition

- **Zero install for end users** — just provide a GitHub URL and a PAT
- **Three-pass parsing** — tree-sitter (deterministic, free) → symbol-index workload reducer (free) → agent reasoning (surgical, only on what's left)
- **Differential updates** — incremental graph patches in seconds, not full rebuilds
- **QnA grounded in the graph** — answers cite specific nodes and files, not hallucinated references

## Architecture Overview

Meridian is structured as **eight top-level components (C1–C8)**. Multi-unit components use sub-letters (e.g. `C3a`, `C4b`).

| C# | Component | Path | Status |
|----|-----------|------|--------|
| C1 | API Gateway | `api/` | built |
| C2 | Orchestrator | `orchestrator/` | built |
| C3 | Ingestion Layer | `ingestion_layer/` | built |
| ↳ C3a | Git Client | `ingestion_layer/repo_cache/` | built |
| ↳ C3b | GitHub MCP Client | `ingestion_layer/github_mcp/` | built |
| C4 | Hybrid Parser | `hybrid_parsing/` | built |
| ↳ C4a | Tree-sitter (Pass 1) | `hybrid_parsing/codebase_parser/` | built |
| ↳ C4ab | Workload Reducer (Pass 1.5) | `hybrid_parsing/workload_reducer/` | built |
| ↳ C4b | Agent Reasoning (Pass 2) | `hybrid_parsing/surgical_agent/` | built |
| ↳ C4c | Tree Indexer | `hybrid_parsing/tree_indexer/` | built |
| C5 | Graph Engine | `graph_engine/` | built |
| ↳ C5a | Graph Builder | `graph_engine/networkX_graph_builder/` | built |
| ↳ C5b | Leiden Clustering | `graph_engine/leiden_clustering/` | built |
| C6 | QnA Agent | `playground/` | built |
| C7 | React Frontend | `frontend/` | built |
| C8 | Persistence (SQLite) | `db/` (`meridian.db`) | built |

The Anthropic SDK wrappers used by C2 / C4b / C6 live in `sdk/` — `sdk/claude_client.py` (singleton `ClaudeSDKClient`) and `sdk/claude_code_agent.py` (Agent SDK with grep/glob/read tools). Both honour `ANTHROPIC_MODEL` and route through Bedrock when `CLAUDE_CODE_USE_BEDROCK=1`.

### C1 — API Gateway

**Tech:** FastAPI. Entry point: `api/main.py::create_app`.

**Role:** REST endpoints, serves the built React SPA from `api/static/` (when present). Validates requests and delegates to the orchestrator (C2).

**Endpoints:**
- `POST /auth/register` — create a user account (`api/routes/user_services/router.py`)
- `POST /auth/login` — returns a 24h JWT
- `POST /repos/sync` — single dispatch: orchestrator picks FULL or PATCH internally (`api/routes/repos.py`). PAT is passed per-request via the `X-GitHub-PAT` header and never stored
- `GET /repos` — list the caller's graphs (metadata only, no payload) (`api/routes/graphs.py`)
- `GET /graph?graph_id=...` — fetch the full graph payload (nodes + edges) by id
- `DELETE /repos/{graph_id}` — evict graph + tree + history + clone record + on-disk cache directory; sync_runs are intentionally left as orphaned audit rows
- `WS /playground/{graph_id}?token=<JWT>&query=<initial>&agentic=<bool>` — multi-turn streaming QnA (C6). The route in `api/routes/graphs.py` is a thin shell; all session orchestration lives in `orchestrator/qna_chat.py::run_playground_session`. JWT goes via the `token` query param because browsers can't set headers on WS

All `/repos`, `/graph` routes require a valid JWT. Users can only access their own graphs (every query is scoped by `user_id` from the JWT via `api/deps.py::get_current_user_id`). The `/playground/{graph_id}` WS performs the same scoping inside `orchestrator.qna_chat`.

**TODO:** `WS /repos/{graph_id}/status` (build progress stream) is not yet wired.

### C2 — Orchestrator

**Tech:** Plain async Python plus the Claude Agent SDK (used inside C4b).

**Role:** Single entry point invoked by C1. Decides FULL vs PATCH and chains the stages.

- `orchestrator/orchestrator.py::sync_repo(repo_url, pat, branch, user_id)` — reads `has_active_graph(repo_url, branch)` and dispatches.
- `orchestrator/full_build.py::full_build` — clone → C4a → C4ab → C4b (only if refs remain) → C4c → C5a → C5b → `link_tree_to_graph` → `record_sync_run` → `record_graph_version`.
- `orchestrator/patch_build.py::patch_sync` — `get_active_graph` → `pull_repo` → no-op short-circuit if HEAD didn't move → `_split_diff` → re-parse fresh files via `parse_files` → `mutate_tree` → re-resolve only delta ambiguous refs → `update_tree` (preserves `tree_id`) → C5a → C5b → audit row → snapshot. MCP commit-log enrichment runs in parallel as a best-effort background task.
- DB helpers live in `orchestrator/utils/db_utils.py`: `has_active_graph`, `get_active_graph` (returns the `(graph_id, tree_id, previous_sha)` tuple), `record_sync_run`.
- `orchestrator/qna_chat.py::run_playground_session` — service handler for the C6 QnA WebSocket. Decodes the JWT, loads the graph + clone path, manages the `QnaSession` lifecycle, and drives the streaming protocol. The FastAPI route is a thin shell that delegates here.

C3, C4, C5 own only primitives — every routing decision lives here.

### C3 — Ingestion Layer

**Hybrid model — rate-limit protection:** GitHub's REST API is capped at 5,000 req/hr per PAT. Bulk file fetching via the GitHub MCP would burn that on a single medium repo. So:

- **Bulk transfer** uses `git clone` / `git pull` via subprocess (git protocol — not rate-limited).
- **Metadata enrichment** uses the GitHub MCP server (commits between SHAs, PRs, issues) — low-volume, high-value.

#### C3a — Git Client

`ingestion_layer/repo_cache/clone_repo.py::clone_repo` and `pull_repo.py::pull_repo`. Working copies are written to the on-disk cache root, default `ingestion_layer/repo_cache/codebase/<repo>` (configurable via the `CACHE_ROOT` env var). The cache is purely ephemeral — graph data lives in C8.

`pull_repo` resolves the diff between `previous_sha` and `HEAD` into a typed `PullResult` with `changed_files: list[FileChange]` (status `A`/`M`/`D`/`R` plus `old_path` for renames). `_split_diff` in `patch_build.py` partitions that into `(stale_paths, fresh_paths)` for the surgical re-parse.

#### C3b — GitHub MCP Client

`ingestion_layer/github_mcp/client.py::GithubMCPClient` (async context manager). Currently used by `patch_build` to log commits between SHAs as a best-effort enrichment — failures degrade silently.

### C4 — Hybrid Parser

The hybrid parser turns a cloned repo on disk into a durable parse tree. Pass 1 is deterministic and free; Pass 1.5 is a free symbol-index reducer; Pass 2 is surgical and only fires on what survives the first two passes; the indexer persists the result.

#### C4a — Tree-sitter (Pass 1)

`hybrid_parsing/codebase_parser/parser.py` — entry points `parse_codebase(repo)` (full) and `parse_files(repo, paths)` (file-scoped, used by PATCH).

- 25-language coverage via `tree-sitter-language-pack` (`languages.py::EXT_TO_LANG`).
- Per-language walkers in `walkers/` extract nodes (modules / classes / functions / methods) and EXTRACTED edges (imports, same-file calls, contains, inherits, decorates).
- Cross-file / dynamic refs are emitted as `AmbiguousRef` for downstream resolution.

#### C4ab — Workload Reducer (Pass 1.5)

`hybrid_parsing/workload_reducer/reducer.py::reduce_workload`. Routes each `AmbiguousRef` to a language-specific reducer (`reducer_python.py`, `reducer_java.py`, `reducer_javascript.py`) and falls back to a generic reducer for the rest. Builds a project-wide symbol index and resolves the easy refs without an LLM call.

Typical mixed-repo split: ~88% dropped (external/stdlib, no project match), ~10% resolved (unique cross-file matches), ~2% passed through to C4b.

#### C4b — Agent Reasoning (Pass 2)

`hybrid_parsing/surgical_agent/resolver.py::resolve_ambiguous`. Uses the Agent SDK with `Read` / `Glob` / `Grep` tools — surgical reads, not whole-file ingestion — to resolve the ambiguous refs the reducer couldn't. Produces `INFERRED` edges. Only runs when `parse_result.ambiguous` is non-empty after Pass 1.5.

#### C4c — Tree Indexer

`hybrid_parsing/tree_indexer/indexer.py`. Three operations:
- `index_tree(parse_result, last_commit_sha)` — FULL: insert a `trees` row with status `READY`, returns `tree_id`.
- `load_tree_as_parse_result(tree_id)` — PATCH: rehydrate `tree_data` JSON back into a `ParseResult`.
- `mutate_tree(existing, stale_files, delta)` — PATCH: drop nodes/edges/ambiguous from `stale_files`, splice in the delta.
- `update_tree(tree_id, merged, last_commit_sha)` — PATCH: UPDATE the existing row in place (`tree_id` is preserved across syncs).

### C5 — Graph Engine

#### C5a — Graph Builder

`graph_engine/networkX_graph_builder/builder.py::build_graph(tree_id) -> GraphBuildResult`. Loads the parse tree (scoped on `status = READY` at the SQL layer), produces a `networkx.MultiDiGraph` (directed, multi-edge), and synthesises `type = "external"` nodes for edge endpoints not present in the tree (cross-repo imports, module globals tree-sitter doesn't extract).

The orchestrator persists the build result via `graph_engine/utils/db_utils.py::persist_graph` — UPSERT into `graphs` keyed on `(user_id, repo_url, branch)`, with `graph_data = {nodes, edges}`, `status = 'BUILDING'`. The `graph_id` is returned to the client immediately, even before C5b runs.

**Edge types:** `IMPORTS`, `CALLS`, `CONTAINS`, `INHERITS`, `DECORATES`, `RELATES_TO`, `DEPENDS_ON`. **Confidence:** `EXTRACTED` (tree-sitter / reducer) or `INFERRED` (agent). Unknown edge types are dropped and counted in `edges_dropped`.

**Node example (within `graph_data` JSON):**
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

#### C5b — Leiden Clustering

`graph_engine/leiden_clustering/clusterer.py::cluster_graph(graph_id) -> ClusterResult`. Loads the C5a graph, projects the `MultiDiGraph` to an undirected weighted simple graph (parallel + reverse edges summed), runs Leiden, writes `community` / `is_god` / `is_orphan` onto each node, and UPDATEs the same `graphs` row in place — flipping `status` to `READY` and setting `community_count`.

`is_god` flags hubs whose neighbours span 2+ other communities (registries / dispatchers / utilities); `is_orphan` flags isolates (dead-code candidates). Lazy-imports `graspologic` so FastAPI cold start stays under a second.

### C6 — QnA Agent

**Tech:** Claude Agent SDK (`ClaudeSDKClient`). Lives in `playground/`. Multi-turn, streaming, WebSocket-driven.

**Modules:**
- `playground/config.py::QnaConfig` — tuning knobs. `top_k` (seeds per turn, env `QNA_TOP_K`) and `max_turns` (env `QNA_MAX_TURNS`).
- `playground/tools/` — retrieval logic, one file per tool:
  - `search_nodes.py` — keyword-scores every node, returns top-K seeds with pre-fetched immediate neighbours.
  - `get_neighbours.py` — given a node ID, returns all inbound/outbound edges with neighbour metadata; fuzzy-matches on name if the exact ID is not found.
  - `get_community.py` — lists all members of a Leiden community cluster, god nodes first.
  - `__init__.py::build_context(query, graph_data)` — composes all three tools and formats the result as readable text (not raw JSON) for injection into the model prompt.
- `playground/prompts.py::SYSTEM_PROMPT` — single system prompt; expects formatted `<graph_context>` per turn.
- `playground/session.py::QnaSession` — async context manager wrapping one `ClaudeSDKClient`. Calls `build_context` server-side before each turn, injects the result as `<graph_context>`, then streams the response. Reused across turns so prior history stays in the model's context.

**Retrieval pipeline (runs server-side before every user turn):**
1. `search_nodes` — keyword-score all nodes, take top-K seeds.
2. `get_neighbours` — enrich each seed with its full inbound/outbound edge list.
3. `get_community` — fetch cluster context for each unique community seen in the seeds.
4. Format as human-readable text (node name, type, file:line, community, calls/called-by) and inject as `<graph_context>`.

**Session lifecycle:** one `QnaSession` per WebSocket connection; closing the WS discards history. The frontend keeps the socket open across in-app navigation so the user can return to the chat — closing the browser tab kills the conversation.

**Wire protocol** (handled by `orchestrator/qna_chat.py`):
- Server → client: `{"type":"ready"}`, `{"type":"delta","text":"..."}`, `{"type":"done"}`, `{"type":"error","message":"..."}`
- Client → server: `{"query":"..."}` per turn (or raw text — both accepted)
- Close codes: `4401` invalid token, `4404` graph not found / not owned, `4409` graph not READY, `1011` internal error

### C7 — React Frontend

**Tech:** React 18 + Vite + TypeScript, `react-force-graph-3d` (3D WebGL), Zustand for state, Tailwind for styling. Lives in `frontend/`. Built assets are copied into `api/static/` and served by FastAPI's SPA fallback.

**Components (`frontend/src/components/`):**
- `LoginPage` / `RegisterPage` — auth flow against `/auth/*`
- `RepoDashboard` — submit URL + PAT, list graphs, drive `POST /repos/sync` and poll for status (WebSocket-driven progress is still TODO)
- `GraphCanvas` — 3D force graph, semantic zoom is partial
- `NodeSidebar` — node detail panel
- `PlaygroundLauncher` / `PlaygroundChat` — opens a `WS /playground/{graph_id}` connection and drives the multi-turn streaming chat (deltas, thinking indicator, error states)
- `SearchBar`, `StatsBar`, `ThemeToggle`

State stores: `authStore.ts` (JWT), `store.ts` (graph data), `themeStore.ts`.

**TODO (per `.TODO`):** WebSocket-driven progress, full semantic zoom (community super-nodes at low zoom, god nodes + boundaries at mid).

### C8 — Persistence

**Tech:** SQLite, default `db/meridian.db`. Six tables: `users`, `graphs`, `trees`, `repo_clones`, `sync_runs`, `graph_history`. Engine + session lifecycle in `db/database.py`; entities in `db/entities/`. PRAGMA `foreign_keys=ON` is set on every connection.

## Request Flow

C1 validates and delegates to C2. C2 is the only component that decides what runs, in what order, against which primitives. C3, C4, C5 are leaves.

**FULL build (no active graph for `(repo_url, branch)`):**
```
Client → C1 → C2 (has_active_graph → False)
    ├─→ C3a clone_repo + persist_clone
    ├─→ C4a parse_codebase  ─┐
    ├─→ C4ab reduce_workload  │ _parse_and_resolve
    ├─→ C4b resolve_ambiguous ┘   (only if refs remain)
    ├─→ C4c index_tree → tree_id
    ├─→ C5a build_graph + persist_graph (status=BUILDING) → graph_id
    ├─→ C5b cluster_graph (status flips to READY)
    ├─→ link_tree_to_graph
    ├─→ record_sync_run (mode=FULL, status=SUCCESS)
    └─→ record_graph_version (immutable history snapshot)
```

**PATCH update (active graph exists):**
```
Client → C1 → C2 (has_active_graph → True)
    ├─→ get_active_graph → (graph_id, tree_id, previous_sha)
    ├─→ C3a pull_repo (re-clones if cache evicted)  + persist_clone
    │   └─ no-op short-circuit if HEAD == previous_sha
    ├─→ C3b commits_between (parallel, best-effort log)
    ├─→ load_tree_as_parse_result(tree_id)
    ├─→ C4a parse_files(fresh_paths)
    ├─→ mutate_tree(existing, stale_paths, delta)
    ├─→ C4ab + C4b on delta.ambiguous only (carry-over refs untouched)
    ├─→ update_tree (preserves tree_id)
    ├─→ C5a build_graph + persist_graph
    ├─→ C5b cluster_graph
    ├─→ record_sync_run (mode=PATCH)
    └─→ record_graph_version
```

## Database Schema

**`users`** — `user_id` (UUID, PK), `email` (UNIQUE), `display_name`, `github_username`, `password` (bcrypt hash, never plaintext), `role` (`'admin'` | `'member'`), timestamps.

**`graphs`** — `graph_id` (UUID, PK), `user_id` FK, `repo_clone_id` FK (ON DELETE SET NULL), `repo_url`, `branch`, `last_commit_sha`, `graph_data` (JSON: `{nodes, edges}`), `status` (`BUILDING` | `READY` | `ERROR`), `node_count`, `edge_count`, `community_count`, `error_message`, timestamps. UNIQUE `(user_id, repo_url, branch)` — that's `persist_graph`'s upsert conflict target.

**`trees`** — `tree_id` (UUID, PK), `graph_id` FK UNIQUE (ON DELETE CASCADE), `tree_data` (JSON: `{repo, root, files_parsed, files_skipped, languages, errors, nodes, edges, ambiguous}`), `last_commit_sha`, `status`, `node_count`, `edge_count`, `ambiguous_count`, timestamps. `graph_id` is currently nullable (the FULL pipeline links it after C5b succeeds via `link_tree_to_graph`).

**`repo_clones`** — `repo_id` (PK, hash of repo_url), `user_id` FK (ON DELETE CASCADE), `owner`, `repo`, `repo_url`, `branch`, `path`, `last_commit_sha`, `size_bytes`, `cloned_at`, `last_accessed_at`, `evicted_at`. UNIQUE `(user_id, owner, repo, branch)`. Rows are kept as tombstones after eviction so a re-clone can resume from `last_commit_sha`.

**`sync_runs`** — `run_id` (UUID, PK), `graph_id` FK (ON DELETE CASCADE), `mode` (`FULL` | `PATCH`), `status` (`RUNNING` | `SUCCESS` | `ERROR`), `triggered_by` (`auto` | `manual_rebuild`), `previous_sha`, `current_sha`, delta counts (`nodes_added/removed`, `edges_added/removed`, `ambiguous_added/removed`), `error_message`, `started_at`, `finished_at`. Currently inserted only at the end of a build; opening a `RUNNING` row at dispatch start is a TODO.

**`graph_history`** — `history_id` (UUID, PK), `graph_id` FK (ON DELETE CASCADE), `version` (monotonic per `graph_id`), `run_id` FK (ON DELETE SET NULL), `graph_data` snapshot, `last_commit_sha`, count denormalisations, `created_at`. UNIQUE `(graph_id, version)`. Written by `record_graph_version` only on successful builds where `graph_data` actually changed — it's an immutable audit log of "what the graph looked like at this build", separate from the live `graphs` row.

**Lifecycle rules:**
- `graphs.status`: `BUILDING` (set by `persist_graph`) → `READY` (set by `cluster_graph`), or `BUILDING` → `ERROR`. `graph_data` is non-null as soon as C5a finishes; the row is mutated (not replaced) once C5b runs.
- `trees.status`: `BUILDING` during C4a/C4b → `READY` after C4c commits. PATCH mutates the existing row in place.
- Graphs persist until an explicit `DELETE /repos/{graph_id}`. `node_count` / `edge_count` reflect the unclustered graph at upsert; `community_count` is set by C5b (0 while `BUILDING`).
- `DELETE /repos/{graph_id}` cascades the tree, history, and clone record (and rmtrees the cache directory) but intentionally leaves `sync_runs` rows orphaned as a historical audit trail.

## Storage Model

**Ephemeral — repo cache:** default `ingestion_layer/repo_cache/codebase/<repo>/` (override via `CACHE_ROOT`). Holds `.git/` + working tree. Loss impact: zero — re-clone on next sync. Auto-eviction (TTL + LRU disk budget) is a TODO; the `evicted_at` column exists for it.

**Durable — SQLite:** default `db/meridian.db`. Holds users, graphs, trees, clone tombstones, sync history, immutable graph snapshots. Loss impact: catastrophic. Back this up.

**Re-clone scenario:** when the cache for an existing graph is missing, `pull_repo` falls back to a full clone, then resumes the diff against `last_commit_sha` from the surviving `repo_clones` / `graphs` row.

## Authentication

JWT-based. `POST /auth/register` → bcrypt the password → store in `users.password`. `POST /auth/login` → verify bcrypt → return a 24h `HS256` token signed with the `JWT_SECRET` env var (default is a dev placeholder — override in prod).

`api/deps.py::get_current_user_id` is the only thing that mints a `user_id` for downstream routes; every DB query in `graphs.py`, `repos.py`, and the orchestrator flows through it.

There is currently a `_SYSTEM_USER_ID = "system"` placeholder in `user_services/router.py` and `graph_engine/utils/db_utils.py` — it's slated for removal once `trees.graph_id` and `repo_clones.user_id` flip from nullable to NOT NULL (see `.TODO`).

## Key Design Decisions

1. **No LSP** — Agent SDK grep/glob/read tools handle dynamic patterns LSP can't, load only what's needed, and require no language-server infrastructure.
2. **Tree-sitter over Python `ast`** — 25-language coverage vs Python-only.
3. **Three-pass parsing, not two** — Pass 1.5 (workload reducer) drops ~88% of ambiguous refs without an LLM call. Only what survives the symbol-index reducer hits C4b. Original CLAUDE.md described this as two-pass; the reducer was added because Pass 2 alone was burning tokens on cross-file refs that had a single deterministic match.
4. **Hybrid ingestion** — `git clone` / `git pull` for bulk transfer (no API rate limit), GitHub MCP only for metadata enrichment (PRs, commits between SHAs).
5. **Differential updates from day one** — PATCH re-parses only changed files via `parse_files`, mutates the stored `trees` row in place (preserves `tree_id`), and re-resolves only the delta's ambiguous refs.
6. **Single dispatch endpoint** — `POST /repos/sync` covers both initial build and re-sync; the orchestrator picks FULL vs PATCH from `has_active_graph`. Clients don't need to pre-check.
7. **PAT per-request** — passed via `X-GitHub-PAT` header on each `/repos/sync` call. Never persisted, never logged.
8. **`graph_history` for immutable snapshots** — the live `graphs` row is mutated in place across syncs; `graph_history` keeps an append-only record of what the graph looked like at every successful build, linked to the `sync_runs` row that produced it.
9. **Graphs persist until explicit delete** — no TTL, no auto-eviction. `DELETE /repos/{graph_id}` is the only path.
10. **C8 is its own component, not a leaf** — every other component reads/writes through it via SQLAlchemy. There is no service in front.

## Deployment

Single Docker image. FastAPI serves both the API and the built React SPA from `api/static/`. SQLite is embedded — no separate DB process.

**Container contents:** FastAPI + uvicorn (C1, serves static SPA), git CLI (C3a), `tree-sitter-language-pack` (C4a), Agent SDK runtime (C4b), NetworkX + graspologic (C5), SQLite (C8).

**External network:** GitHub git protocol (clone/pull, not rate-limited), GitHub REST API via MCP (metadata only, ≤20 calls/sync), Anthropic API (or AWS Bedrock when `CLAUDE_CODE_USE_BEDROCK=1`) for C4b and C6.

## What NOT to Do

- Do NOT use the GitHub MCP `get_file_contents` for bulk file fetching — burns 1 API call per file and exhausts the 5,000/hr limit. Use `git clone` / `git pull` instead.
- Do NOT use LSP or language servers — explicitly rejected.
- Do NOT use Python's built-in `ast` — tree-sitter is multi-language.
- Do NOT call the Anthropic API directly — go through `sdk/claude_client.py` (single-shot) or `sdk/claude_code_agent.py` (Agent SDK with tools).
- Do NOT auto-delete graphs — only `DELETE /repos/{graph_id}` removes them.
- Do NOT skip the JWT scope — every `/repos`, `/graph` query must filter by `user_id` from `get_current_user_id`.
- Do NOT store plaintext passwords or PATs — bcrypt for passwords, no persistence at all for PATs.
- Do NOT send full file contents to the LLM — C4b uses surgical Read/Glob/Grep.
- Do NOT rebuild the full graph on sync when an active graph exists — `patch_sync` mutates the stored tree and re-clusters in place.
- Do NOT pass unsanitized user-provided repo URLs to subprocess — `clone_repo` must validate.
- Do NOT treat the cache directory as durable — C8 is the source of truth.
