"""API tests for POST /auth/register and POST /auth/login.

Uses the session-scoped `app_client` fixture from test/conftest.py.
Each test that needs a fresh user generates a unique email so tests
don't interfere with each other.
"""

import uuid


def _unique_email() -> str:
    return f"user_{uuid.uuid4().hex[:10]}@example.com"


def _register(client, email: str, password: str = "securepass1", display_name: str = "Alice"):
    return client.post(
        "/auth/register",
        json={"email": email, "display_name": display_name, "password": password},
    )


# ── register ──────────────────────────────────────────────────────────────────


def test_register_returns_201_with_user_fields(app_client):
    resp = _register(app_client, _unique_email())
    assert resp.status_code == 201
    body = resp.json()
    assert "user_id" in body
    assert body["role"] == "member"
    assert body["email"].endswith("@example.com")


def test_register_duplicate_email_returns_409(app_client):
    email = _unique_email()
    _register(app_client, email)
    resp = _register(app_client, email)
    assert resp.status_code == 409


def test_register_reserved_email_returns_422(app_client):
    resp = _register(app_client, "system@meridian.local")
    assert resp.status_code == 422


def test_register_password_too_short_returns_422(app_client):
    resp = _register(app_client, _unique_email(), password="short")
    assert resp.status_code == 422


def test_register_invalid_email_returns_422(app_client):
    resp = _register(app_client, "not-an-email", password="securepass1")
    assert resp.status_code == 422


def test_register_missing_display_name_returns_422(app_client):
    resp = app_client.post(
        "/auth/register",
        json={"email": _unique_email(), "password": "securepass1"},
    )
    assert resp.status_code == 422


# ── login ─────────────────────────────────────────────────────────────────────


def test_login_returns_bearer_token(app_client):
    email, pw = _unique_email(), "securepass1"
    _register(app_client, email, pw)
    resp = app_client.post("/auth/login", json={"email": email, "password": pw})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert body["email"] == email


def test_login_wrong_password_returns_401(app_client):
    email = _unique_email()
    _register(app_client, email, "correctpass1")
    resp = app_client.post("/auth/login", json={"email": email, "password": "wrongpassword"})
    assert resp.status_code == 401


def test_login_unknown_email_returns_401(app_client):
    resp = app_client.post(
        "/auth/login",
        json={"email": "nobody@nowhere.example.com", "password": "whatever123"},
    )
    assert resp.status_code == 401


def test_login_token_is_decodable_jwt(app_client):
    import jwt as pyjwt

    email, pw = _unique_email(), "securepass1"
    reg = _register(app_client, email, pw)
    user_id = reg.json()["user_id"]

    login = app_client.post("/auth/login", json={"email": email, "password": pw})
    token = login.json()["access_token"]

    payload = pyjwt.decode(
        token,
        "meridian-dev-secret-change-in-prod",
        algorithms=["HS256"],
    )
    assert payload["sub"] == user_id
