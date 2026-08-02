# Meridian — Improvement Backlog

Audited: 2026-07-26. Issues ranked by severity within each section.

---

## Critical

### ~~C1 — Cross-user graph data isolation bug~~ ✅ FIXED
**File:** `orchestrator/utils/db_utils.py:33–78`

`has_active_graph` and `get_active_graph` filter only on `(repo_url, branch)`, not `user_id`. If two users sync the same GitHub URL, the second user's build routes to PATCH mode against the first user's graph — mutating another user's data with a different PAT.

**Fix:** Add `user_id` to the `WHERE` clause in both functions. Verify every caller passes a `user_id`.

**Implemented:** Added `user_id: str` to both function signatures and `Graph.user_id == user_id` to both WHERE clauses. Added `if not user_id: raise` guards in `orchestrator.py` and `patch_build.py` so None can never slip through. Updated the `api/routes/repos.py` pre-flight call to pass `user_id`.

---

### ~~C2 — Sync endpoint blocks the only Uvicorn worker~~ ✅ FIXED
**File:** `api/routes/repos.py:30`

`POST /repos/sync` awaits the full clone → parse → cluster pipeline synchronously in the HTTP request cycle (potentially 10–30 min on large repos). While a build is running, every other endpoint — including the health check — is unreachable.

**Fix:** Dispatch the build as a background task (e.g. `FastAPI BackgroundTasks` or a task queue). Return `202 Accepted` with the `graph_id` immediately. Clients poll `GET /repos` for status as they already do.

**Implemented:** Route pre-flights with `get_active_graph` (PATCH) or `reserve_graph` (FULL) to lock in a `graph_id`, dispatches `_run_sync` as a `BackgroundTask`, and returns `202` immediately. `mark_graph_error` flips the row to `ERROR` on background task failure. New helpers in `graph_engine/utils/db_utils.py`.

---

### ~~C3 — Zero test coverage for the core pipeline~~ ✅ FIXED
**Files:** entire codebase — no `pytest.ini`, no `conftest.py`, no test files for Meridian's own code

No tests exist for the tree-sitter walkers, workload reducer, tree indexer, graph builder, Leiden clusterer, DB utils, orchestrator, or API routes. The only `test.py` in the root is an ad-hoc SDK smoke test.

**Fix:** Add `pytest` + `httpx` (`TestClient`) as dev dependencies. Start with unit tests for `mutate_tree`, `reduce_workload`, `build_graph`, and the API routes. Integration tests for the full FULL/PATCH pipeline against a small fixture repo.

**Implemented:** Added `pytest>=8.0`, `httpx>=0.27`, `pytest-mock>=3.14` to `[project.optional-dependencies] dev` in `pyproject.toml`, along with `[tool.pytest.ini_options]` pointing at `test/` with `pythonpath = ["."]`. Created `test/` with:
- `conftest.py` — session-scoped `app_client` (temp SQLite, lifespan patched), `register_and_login`, `insert_ready_graph` helpers.
- `unit/test_mutate_tree.py` — 12 cases covering node removal, delta splice, edge drop/keep semantics (truly-removed vs returning), ambiguous ref pruning, and metadata merging.
- `unit/test_reduce_workload.py` — 15 cases covering unique resolution → IMPORTS/CALLS/INHERITS/DECORATES edges, no-candidate drop, multi-candidate pass-through, same-package heuristic, and `_parse_import_name` variants.
- `unit/test_build_graph.py` — 8 cases covering empty tree, node attrs, all valid edge types, invalid-type drop, external-node synthesis, count correctness, and graph metadata propagation.
- `api/test_auth.py` — 9 cases: register (happy path, duplicate email, reserved email, short password, invalid email, missing field) and login (happy path, wrong password, unknown email, JWT decode check).
- `api/test_repos.py` — 6 cases: auth guards (missing Authorization, missing PAT, invalid URL), FULL mode (202 + graph_id, BUILDING row confirmed), PATCH mode detection, and C1 cross-user isolation (same URL synced by user B stays FULL).
- `api/test_graphs.py` — 13 cases: list graphs (auth guard, own vs other, empty for new user), get graph (auth guard, 404 for missing, 200 for own, cross-user 404), delete (204, removes from list, nonexistent 404, cross-user 404), skill endpoint (auth guard, 409 for BUILDING, 422 for bad tool, cross-user 404).

---

## High

### H1 — No SQLite WAL mode
**File:** `db/database.py:19–28`

`PRAGMA journal_mode=WAL` is never set. In default journal mode, readers block writers and writers block readers — unnecessary even in the single-worker model.

**Fix:** Add `PRAGMA journal_mode=WAL` to the `@event.listens_for(engine, "connect")` hook alongside `PRAGMA foreign_keys=ON`.

---

### H2 — No database migration system
**File:** `db/database.py:39`

Schema is managed entirely by `Base.metadata.create_all()`, which only creates missing tables. Any column addition, index change, or type change on an existing deployment requires manual intervention or data loss.

**Fix:** Introduce Alembic. Run `alembic init`, configure `env.py` to point at `Base.metadata`, and generate an initial migration from the current schema. All future schema changes go through a versioned migration file.

---

### H3 — No rate limiting on auth or sync endpoints
**Files:** `api/routes/user_services/router.py`, `api/routes/repos.py`

`POST /auth/login` is brute-force-able. `POST /repos/sync` can be spammed to queue expensive AI compute. No per-IP throttle or token bucket is present.

**Fix:** Add `slowapi` middleware. Apply `@limiter.limit("5/minute")` on `/auth/login` and `/auth/register`, and `@limiter.limit("10/hour")` on `/repos/sync`.

---

### ~~H4 — Full graph JSON serialized 3× per build~~ ✅ FIXED
**File:** `graph_engine/utils/db_utils.py`

A single FULL build does: (1) serialize NetworkX graph → JSON and INSERT (`persist_graph`), (2) read that blob back and re-inflate a NetworkX graph for Leiden (`load_graph` inside `cluster_graph`), (3) serialize the enriched graph → JSON and UPDATE (`update_graph_with_clusters`). Three full JSON round-trips and two NetworkX inflations of the same graph.

**Fix:** Pass the already-built `networkx.MultiDiGraph` directly from C5a into C5b instead of persisting then reloading. Persist once after clustering completes.

**Implemented:** `cluster_graph` now accepts an optional `graph: nx.MultiDiGraph` — when provided it skips `load_graph` entirely. `update_graph_with_clusters` was extended to also set `node_count`, `edge_count`, `last_commit_sha`, `repo_clone_id` in the same write, and switched from ORM SELECT+mutate to a Core `UPDATE` to avoid reading back the large `graph_data` blob. Both `full_build` and `patch_build` drop the `persist_graph` call and pass the graph directly to `cluster_graph`. `full_build` calls `reserve_graph` (idempotent UPSERT) to resolve its own `graph_id` without threading it through the call stack.

---

### H5 — BM25 recomputed from scratch on every QnA turn
**File:** `playground/tools/search_nodes.py`

`run()` rebuilds the full IDF index over all nodes on every user message — O(N) work per turn. For a 10k-node graph this is significant latency with no benefit since the graph data doesn't change between turns.

**Fix:** Cache the tokenized corpus and IDF table keyed on `graph_id`. Invalidate the cache when the graph is re-synced (status flips from `BUILDING` to `READY`).

---

### H6 — `graph_history` stores full graph JSON for every version
**Files:** `db/entities/graph_history.py`, `graph_engine/utils/db_utils.py:294–351`

Each successful build appends a complete copy of `graph_data` (potentially multiple MB) to `graph_history`. With frequent syncs on large repos, this balloons the SQLite file indefinitely.

**Fix:** Store only a diff/delta between versions, or cap retention to the last N versions per graph (e.g. 10), pruning older rows in `record_graph_version`. At minimum, document the growth risk and add a manual pruning script.

---

### H7 — Repo cache grows indefinitely
**File:** `db/entities/repo_clone.py`

`evicted_at` exists in the schema but no eviction logic exists anywhere. The `meridian_cache` Docker volume grows without bound as repos accumulate.

**Fix:** Implement a TTL-based eviction job (e.g. evict clones not accessed in 30 days). Set `evicted_at` and `rmtree` the directory. The `pull_repo` re-clone fallback already handles the missing-cache case.

---

## Medium

### M1 — Missing security headers
**File:** `api/main.py`

No `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, or `Strict-Transport-Security` headers are set. The SPA is vulnerable to clickjacking and MIME sniffing.

**Fix:** Add a response middleware that injects these headers on every response. At minimum: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and a `Content-Security-Policy` that restricts `script-src` to `'self'`.

---

### M2 — JWT stored in `sessionStorage` (XSS-readable)
**File:** `frontend/src/authStore.ts:73–79`

The JWT is persisted to `sessionStorage` via zustand-persist. Any injected script can read `sessionStorage.getItem('meridian-auth')`. Combined with absent CSP headers this is a meaningful XSS amplification vector.

**Fix:** Move to an `HttpOnly` cookie managed server-side, or at minimum add CSP headers to reduce XSS risk (see M1).

---

### M3 — JWT secret duplicated across three modules
**Files:** `api/deps.py:11`, `api/routes/user_services/router.py:19`, `orchestrator/qna_chat.py:25`

All three independently read `JWT_SECRET` from env and share the same hardcoded fallback. A typo in any one would silently break token validation.

**Fix:** Extract into a single `api/security.py` module. All three import `JWT_SECRET` from there.

---

### M4 — JWT passed as URL query param for WebSocket
**File:** `api/routes/graphs.py:223`

The token appears in server access logs, browser history, and upstream proxy logs. The comment acknowledges this as a browser WebSocket constraint.

**Fix:** Short of a protocol change, document explicitly in deployment guides that logs must be scrubbed. As an alternative, consider a short-lived one-time ticket token exchanged over REST before upgrading to WebSocket.

---

### M5 — Frontend: WebSocket has no auto-reconnect
**File:** `frontend/src/playgroundStore.ts:132–143`

A transient network hiccup permanently disconnects the chat session. `ws.onclose` sets `status: 'closed'` but takes no automatic reconnect action — the user must click "New chat," losing session history.

**Fix:** Implement exponential-backoff reconnect (e.g. 1 s, 2 s, 4 s, cap at 30 s) in `ws.onclose`. Re-establish the socket and resume from the same `graph_id`. Display a "Reconnecting…" indicator during backoff.

---

### M6 — Build polling never times out
**File:** `frontend/src/components/RepoDashboard.tsx:51–68`

The 3-second `setInterval` poll fires indefinitely. If the backend crashes mid-build, `graph.status` is permanently stuck at `BUILDING` and the polling loop runs forever with no user feedback.

**Fix:** Track `pollingStartedAt` and surface a "Build appears stuck — try re-syncing" message after a configurable threshold (e.g. 20 min). Stop the interval and show a retry button.

---

### M7 — Skill file download failure is silent
**File:** `frontend/src/components/RepoDashboard.tsx:127–133`

```typescript
} catch {
  // silently fail — user can retry
}
```

The download button simply un-spins with no message to the user.

**Fix:** Set an error state and display a toast or inline message: "Download failed — check your connection and try again."

---

### M8 — No structured logging or request middleware
**Files:** throughout (all `logger.*` calls use plain `%s` format)

All log lines emit plain text. In production with log aggregators, structured JSON logging enables filtering by `graph_id`, `user_id`, `mode`, and run ID. No access log middleware records HTTP method, path, status code, or latency.

**Fix:** Switch to `python-json-logger` or structlog. Add a Starlette middleware that logs `{method, path, status_code, latency_ms, user_id}` on every response.

---

### M9 — Health check does not verify DB
**File:** `api/routes/health.py`

Returns `{"status": "ok"}` unconditionally. A dead database, full disk, or failed SQLite open still passes the Docker healthcheck.

**Fix:** Execute a lightweight probe — e.g. `SELECT 1` — inside the health handler. Return `503` if it fails.

---

## Low / Code Quality

### L1 — Two DB round-trips where one suffices
**File:** `orchestrator/orchestrator.py:42–66`

`has_active_graph` runs a `SELECT`, then `get_active_graph` runs another immediately. Could be collapsed into a single query returning `None` or the full `ActiveGraph` tuple.

**Fix:** Replace `has_active_graph` with a `get_active_graph` that returns `Optional[ActiveGraph]`. Update the orchestrator to branch on `None`.

---

### L2 — `skillSlugFor` returns `'meridian'` for every repo
**File:** `frontend/src/components/RepoDashboard.tsx:498–500`

```typescript
function skillSlugFor(_repoUrl: string): string {
  return 'meridian'
}
```

All downloaded skill files share the same slash command `/meridian`. A user with two repos can't have two distinct skill files active at once.

**Fix:** Derive the slug from the repo name (e.g. `owner-repo` from the URL). This already happens on the backend in `skill_generator.py` — surface the same slug in the frontend.

---

### L3 — Dead placeholder: `_SYSTEM_USER_ID` / `_ensure_system_user`
**File:** `graph_engine/utils/db_utils.py:20–24, 102, 146–148, 354–374`

Auth has landed. The `user_id=None` → system-user fallback is a TODO that was never cleaned up.

**Fix:** Remove `_SYSTEM_USER_ID`, `_ensure_system_user`, and all related `if user_id is None` branches. Make `user_id: str` non-optional on `persist_graph`.

---

### L4 — `cache_root()` defined twice with different defaults
**Files:** `ingestion_layer/utils/utils.py:8–15`, `hybrid_parsing/codebase_parser/parser.py:24–83`

Both read `CACHE_ROOT` from env but have different fallback paths. Missing env var routes to different directories.

**Fix:** Define `cache_root()` once (e.g. in `ingestion_layer/utils/utils.py`) and import it in the parser.

---

### L5 — `User.last_login_at` and `RepoClone.evicted_at` never written
**Files:** `db/entities/user.py:27`, `db/entities/repo_clone.py`

Schema columns that exist but have no code writing to them.

**Fix:** Write `last_login_at = datetime.utcnow()` in the login endpoint. Wire `evicted_at` to the eviction job described in H7.

---

### L6 — `load_dotenv()` at module import time in MCP client
**File:** `ingestion_layer/github_mcp/client.py:33`

`load_dotenv()` at import time mutates `os.environ` for the entire process, can mask missing env vars in tests, and is a no-op in container environments where vars are injected directly.

**Fix:** Remove the `load_dotenv()` call from the module. Move it to a single call site at application startup if needed for local dev.

---

### L7 — `test.py` ad-hoc script in the project root
**File:** `test.py`

**Fix:** Move to `scripts/` or remove. It is not a test suite and adds noise to the project root.

---

### L8 — Hardcoded model alias `"haiku"` instead of full model ID
**File:** `hybrid_parsing/surgical_agent/resolver.py:83, 103`

Relies on the Claude Agent SDK accepting a short alias. SDK alias mapping can change without notice.

**Fix:** Use the full model ID (e.g. `claude-haiku-4-5-20251001`) and route it through the `ANTHROPIC_MODEL` env var pattern already used in the rest of the codebase.

---

## Summary

| Severity | Count | Fixed | Remaining |
|----------|-------|-------|-----------|
| Critical | 3 | 3 (C1, C2, C3) | 0 |
| High | 7 | 1 (H4) | 6 |
| Medium | 9 | 0 | 9 |
| Low / Quality | 8 | 0 | 8 |
| **Total** | **27** | **4** | **23** |

### Recommended order of attack

1. ~~**C1** — cross-user isolation bug (data integrity + security)~~ ✅ done
2. ~~**C2** — background task dispatch for sync (availability)~~ ✅ done
3. **H1** — SQLite WAL mode (one-liner, immediate win)
4. **H3** — rate limiting on auth + sync (security)
5. **H2** — Alembic migrations (ops safety before next schema change)
6. ~~**C3** — test coverage (enables safe iteration on everything else)~~ ✅ done
7. **M1 + M2** — security headers + token storage (security hardening)
8. ~~**H4**~~ ✅ done + **H5** — BM25 caching (performance)
9. **M5 + M6** — WebSocket reconnect + polling timeout (UX)
10. **L1–L8** — code quality cleanup (ongoing)
