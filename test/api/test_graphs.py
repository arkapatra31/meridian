"""API tests for /repos (list), /graph (get), DELETE /repos/{id}, and
/graph/{id}/skill.

Cross-user isolation (C1 fix) is exercised explicitly: user B must not
be able to read or delete user A's graphs.
"""

import uuid


def _register_and_login(client) -> tuple[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"graphs_{tag}@example.com"
    pw = "testpassword123"
    client.post(
        "/auth/register",
        json={"email": email, "display_name": f"Graph {tag}", "password": pw},
    )
    resp = client.post("/auth/login", json={"email": email, "password": pw})
    return resp.json()["user_id"], resp.json()["access_token"]


def _insert_graph(user_id: str, status: str = "READY") -> tuple[str, str]:
    """Insert a graph row and return (graph_id, repo_url)."""
    from db.database import get_session
    from db.entities import Graph, GraphStatus

    graph_id = str(uuid.uuid4())
    repo_url = f"https://github.com/testowner/repo-{uuid.uuid4().hex[:6]}"
    with get_session() as session:
        session.add(
            Graph(
                graph_id=graph_id,
                user_id=user_id,
                repo_url=repo_url,
                branch="main",
                status=status,
                graph_data={"nodes": [], "edges": []},
                node_count=0,
                edge_count=0,
                community_count=0,
            )
        )
        session.commit()
    return graph_id, repo_url


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── GET /repos ────────────────────────────────────────────────────────────────


def test_list_graphs_without_auth_returns_403(app_client):
    assert app_client.get("/repos").status_code == 403


def test_list_graphs_returns_only_own_graphs(app_client):
    user_a_id, token_a = _register_and_login(app_client)
    user_b_id, token_b = _register_and_login(app_client)

    graph_a_id, _ = _insert_graph(user_a_id)

    resp_a = app_client.get("/repos", headers=_auth(token_a))
    resp_b = app_client.get("/repos", headers=_auth(token_b))

    assert resp_a.status_code == 200
    assert any(g["graph_id"] == graph_a_id for g in resp_a.json())

    # User B must not see user A's graph.
    assert all(g["graph_id"] != graph_a_id for g in resp_b.json())


def test_list_graphs_empty_for_new_user(app_client):
    _, token = _register_and_login(app_client)
    resp = app_client.get("/repos", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


# ── GET /graph ────────────────────────────────────────────────────────────────


def test_get_graph_without_auth_returns_403(app_client):
    resp = app_client.get("/graph", params={"graph_id": str(uuid.uuid4())})
    assert resp.status_code == 403


def test_get_graph_nonexistent_returns_404(app_client):
    _, token = _register_and_login(app_client)
    resp = app_client.get(
        "/graph",
        params={"graph_id": str(uuid.uuid4())},
        headers=_auth(token),
    )
    assert resp.status_code == 404


def test_get_graph_returns_own_graph(app_client):
    user_id, token = _register_and_login(app_client)
    graph_id, _ = _insert_graph(user_id, status="READY")
    resp = app_client.get("/graph", params={"graph_id": graph_id}, headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["graph_id"] == graph_id
    assert body["status"] == "READY"
    assert isinstance(body["nodes"], list)
    assert isinstance(body["edges"], list)


def test_get_graph_cross_user_returns_404(app_client):
    """User B cannot read user A's graph — C1 isolation check."""
    user_a_id, _ = _register_and_login(app_client)
    _, token_b = _register_and_login(app_client)

    graph_id, _ = _insert_graph(user_a_id)

    resp = app_client.get(
        "/graph",
        params={"graph_id": graph_id},
        headers=_auth(token_b),
    )
    assert resp.status_code == 404


# ── DELETE /repos/{graph_id} ──────────────────────────────────────────────────


def test_delete_graph_returns_204(app_client):
    user_id, token = _register_and_login(app_client)
    graph_id, _ = _insert_graph(user_id)

    resp = app_client.delete(f"/repos/{graph_id}", headers=_auth(token))
    assert resp.status_code == 204


def test_delete_graph_removes_it_from_list(app_client):
    user_id, token = _register_and_login(app_client)
    graph_id, _ = _insert_graph(user_id)

    app_client.delete(f"/repos/{graph_id}", headers=_auth(token))

    resp = app_client.get("/repos", headers=_auth(token))
    assert all(g["graph_id"] != graph_id for g in resp.json())


def test_delete_nonexistent_graph_returns_404(app_client):
    _, token = _register_and_login(app_client)
    resp = app_client.delete(f"/repos/{uuid.uuid4()}", headers=_auth(token))
    assert resp.status_code == 404


def test_delete_cross_user_returns_404(app_client):
    """User B cannot delete user A's graph."""
    user_a_id, _ = _register_and_login(app_client)
    _, token_b = _register_and_login(app_client)

    graph_id, _ = _insert_graph(user_a_id)

    resp = app_client.delete(f"/repos/{graph_id}", headers=_auth(token_b))
    assert resp.status_code == 404


# ── GET /graph/{id}/skill ─────────────────────────────────────────────────────


def test_skill_endpoint_requires_auth(app_client):
    resp = app_client.get(f"/graph/{uuid.uuid4()}/skill", params={"tool": "claude_code"})
    assert resp.status_code == 403


def test_skill_endpoint_returns_409_for_building_graph(app_client):
    user_id, token = _register_and_login(app_client)
    graph_id, _ = _insert_graph(user_id, status="BUILDING")

    resp = app_client.get(
        f"/graph/{graph_id}/skill",
        params={"tool": "claude_code"},
        headers=_auth(token),
    )
    assert resp.status_code == 409


def test_skill_endpoint_returns_422_for_unsupported_tool(app_client):
    user_id, token = _register_and_login(app_client)
    graph_id, _ = _insert_graph(user_id, status="READY")

    resp = app_client.get(
        f"/graph/{graph_id}/skill",
        params={"tool": "notepad_plus_plus"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


def test_skill_endpoint_cross_user_returns_404(app_client):
    user_a_id, _ = _register_and_login(app_client)
    _, token_b = _register_and_login(app_client)

    graph_id, _ = _insert_graph(user_a_id, status="READY")

    resp = app_client.get(
        f"/graph/{graph_id}/skill",
        params={"tool": "claude_code"},
        headers=_auth(token_b),
    )
    assert resp.status_code == 404
