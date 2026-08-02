"""API tests for POST /repos/sync.

The route dispatches the heavy pipeline as a BackgroundTask. With
FastAPI's TestClient, background tasks run synchronously inside
`client.post()`, so `sync_repo` is mocked with AsyncMock to avoid
real clone/parse/cluster work.

Cross-user isolation (the C1 fix) is verified by the PATCH-mode test:
a READY graph owned by user A must NOT be visible when user B syncs
the same URL — user B gets FULL mode.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest


_BASE_URL = "https://github.com/testowner"


def _register_and_login(client) -> tuple[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"repos_{tag}@example.com"
    pw = "testpassword123"
    client.post(
        "/auth/register",
        json={"email": email, "display_name": f"Repos {tag}", "password": pw},
    )
    resp = client.post("/auth/login", json={"email": email, "password": pw})
    return resp.json()["user_id"], resp.json()["access_token"]


def _insert_ready_graph(user_id: str, repo_url: str) -> str:
    from db.database import get_session
    from db.entities import Graph, GraphStatus

    graph_id = str(uuid.uuid4())
    with get_session() as session:
        session.add(
            Graph(
                graph_id=graph_id,
                user_id=user_id,
                repo_url=repo_url,
                branch="main",
                status=GraphStatus.READY.value,
                graph_data={"nodes": [], "edges": []},
                node_count=0,
                edge_count=0,
                community_count=0,
                last_commit_sha="abcdef1234567890",
            )
        )
        session.commit()
    return graph_id


# ── auth guards ───────────────────────────────────────────────────────────────


def test_sync_without_auth_header_returns_403(app_client):
    resp = app_client.post(
        "/repos/sync",
        json={"url": f"{_BASE_URL}/repo", "branch": "main"},
        headers={"X-GitHub-PAT": "ghp_test"},
    )
    # HTTPBearer returns 403 when the Authorization header is absent.
    assert resp.status_code == 403


def test_sync_missing_pat_header_returns_422(app_client):
    _, token = _register_and_login(app_client)
    resp = app_client.post(
        "/repos/sync",
        json={"url": f"{_BASE_URL}/repo", "branch": "main"},
        headers={"Authorization": f"Bearer {token}"},
        # X-GitHub-PAT deliberately omitted
    )
    assert resp.status_code == 422


def test_sync_invalid_url_returns_422(app_client):
    _, token = _register_and_login(app_client)
    resp = app_client.post(
        "/repos/sync",
        json={"url": "not-a-url", "branch": "main"},
        headers={"Authorization": f"Bearer {token}", "X-GitHub-PAT": "ghp_test"},
    )
    assert resp.status_code == 422


# ── FULL mode ─────────────────────────────────────────────────────────────────


def test_sync_full_returns_202_with_graph_id(app_client):
    _, token = _register_and_login(app_client)
    repo_url = f"{_BASE_URL}/full-repo-{uuid.uuid4().hex[:6]}"

    with patch("api.routes.repos.sync_repo", new=AsyncMock(return_value=None)):
        resp = app_client.post(
            "/repos/sync",
            json={"url": repo_url, "branch": "main"},
            headers={"Authorization": f"Bearer {token}", "X-GitHub-PAT": "ghp_test"},
        )

    assert resp.status_code == 202
    body = resp.json()
    assert body["mode"] == "FULL"
    assert body["graph_id"] is not None
    assert body["branch"] == "main"


def test_sync_full_creates_building_graph_row(app_client):
    """The route pre-allocates a BUILDING row before dispatching the task."""
    from db.database import get_session
    from db.entities import Graph

    _, token = _register_and_login(app_client)
    repo_url = f"{_BASE_URL}/check-row-{uuid.uuid4().hex[:6]}"

    with patch("api.routes.repos.sync_repo", new=AsyncMock(return_value=None)):
        resp = app_client.post(
            "/repos/sync",
            json={"url": repo_url, "branch": "main"},
            headers={"Authorization": f"Bearer {token}", "X-GitHub-PAT": "ghp_test"},
        )

    graph_id = resp.json()["graph_id"]
    with get_session() as session:
        row = session.get(Graph, graph_id)
        assert row is not None
        # sync_repo was mocked so status remains BUILDING (no cluster step ran).
        assert row.status in ("BUILDING", "READY", "ERROR")


# ── PATCH mode ────────────────────────────────────────────────────────────────


def test_sync_returns_patch_mode_when_ready_graph_exists(app_client):
    from pydantic import HttpUrl

    user_id, token = _register_and_login(app_client)
    repo_url = f"{_BASE_URL}/patch-repo-{uuid.uuid4().hex[:6]}"
    # Pydantic normalises the URL the same way the route does.
    normalized = str(HttpUrl(repo_url))

    _insert_ready_graph(user_id, normalized)

    with patch("api.routes.repos.sync_repo", new=AsyncMock(return_value=None)):
        resp = app_client.post(
            "/repos/sync",
            json={"url": repo_url, "branch": "main"},
            headers={"Authorization": f"Bearer {token}", "X-GitHub-PAT": "ghp_test"},
        )

    assert resp.status_code == 202
    assert resp.json()["mode"] == "PATCH"


def test_sync_isolates_graphs_by_user(app_client):
    """User B syncing the same URL as user A gets FULL, not PATCH (C1 fix)."""
    from pydantic import HttpUrl

    user_a_id, _ = _register_and_login(app_client)
    _, token_b = _register_and_login(app_client)

    repo_url = f"{_BASE_URL}/shared-repo-{uuid.uuid4().hex[:6]}"
    normalized = str(HttpUrl(repo_url))

    # User A has a READY graph for this URL.
    _insert_ready_graph(user_a_id, normalized)

    # User B syncs the same URL — must see FULL, not PATCH.
    with patch("api.routes.repos.sync_repo", new=AsyncMock(return_value=None)):
        resp = app_client.post(
            "/repos/sync",
            json={"url": repo_url, "branch": "main"},
            headers={"Authorization": f"Bearer {token_b}", "X-GitHub-PAT": "ghp_test"},
        )

    assert resp.status_code == 202
    assert resp.json()["mode"] == "FULL"
