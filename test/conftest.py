"""Shared test fixtures and helpers for the Meridian test suite.

The session-scoped `app_client` fixture points FastAPI at an isolated
temp SQLite DB so tests never touch `db/meridian.db`.  The lifespan's
`init_db` / `dispose` are patched to prevent them from reinitialising
the engine mid-session or tearing it down prematurely.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

_JWT_SECRET = "meridian-dev-secret-change-in-prod"
_JWT_ALGORITHM = "HS256"


# ── public utilities ───────────────────────────────────────────────────────────


def mint_token(user_id: str) -> str:
    """Mint a 1-hour JWT for the given user_id using the dev secret."""
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def register_and_login(client: TestClient) -> tuple[str, str]:
    """Register a fresh unique user and return (user_id, access_token)."""
    tag = uuid.uuid4().hex[:8]
    email = f"test_{tag}@example.com"
    password = "testpassword123"

    reg = client.post(
        "/auth/register",
        json={"email": email, "display_name": f"Test {tag}", "password": password},
    )
    assert reg.status_code == 201, f"register failed: {reg.text}"
    user_id = reg.json()["user_id"]

    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, f"login failed: {login.text}"
    return user_id, login.json()["access_token"]


def insert_ready_graph(user_id: str, repo_url: str, branch: str = "main") -> str:
    """Insert a READY graphs row directly and return the graph_id.

    Used by tests that need an existing graph without running the full pipeline.
    The caller's user_id must already exist in the users table.
    """
    from db.database import get_session
    from db.entities import Graph, GraphStatus

    graph_id = str(uuid.uuid4())
    with get_session() as session:
        session.add(
            Graph(
                graph_id=graph_id,
                user_id=user_id,
                repo_url=repo_url,
                branch=branch,
                status=GraphStatus.READY.value,
                graph_data={"nodes": [], "edges": []},
                node_count=0,
                edge_count=0,
                community_count=0,
                last_commit_sha="deadbeefdeadbeef",
            )
        )
        session.commit()
    return graph_id


# ── session fixture ────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def app_client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    """Session-scoped TestClient backed by an isolated temp SQLite DB.

    Strategy:
      1. Call `db.database.init_db(tmp_path)` to set the module globals
         (_engine, _SessionLocal) to the test DB.
      2. Patch `api.main.init_db` and `api.main.dispose` with no-ops so the
         app lifespan doesn't reinitialise the engine (which would use the
         module-default DB_PATH) or dispose it prematurely.
      3. Yield the TestClient; restore originals and dispose the test engine
         when the session ends.
    """
    db_path = tmp_path_factory.mktemp("db") / "test_meridian.db"

    import db.database as db_module

    engine = db_module.init_db(db_path)

    # Prevent the lifespan from touching the default prod DB.
    import api.main as main_module

    _orig_init = main_module.init_db
    _orig_dispose = main_module.dispose
    main_module.init_db = lambda *a, **kw: engine
    main_module.dispose = lambda: None

    from api.main import create_app

    with TestClient(create_app()) as client:
        yield client

    main_module.init_db = _orig_init
    main_module.dispose = _orig_dispose
    db_module.dispose()
