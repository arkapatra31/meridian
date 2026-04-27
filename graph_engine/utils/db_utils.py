"""Database queries used by the graph engine (C8/C9/C10)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import networkx as nx
from sqlalchemy import select

from db.database import get_session
from db.entities import Graph, GraphStatus, Tree, TreeStatus, User

logger = logging.getLogger("meridian.graph_engine.db_utils")

# Placeholder user that owns every graph until auth/JWT is wired up.
# TODO(auth): drop this fixture once `sync_repo` receives a real user_id from
# the JWT. The schema (graphs.user_id NOT NULL FK) is intentionally strict —
# we satisfy it here rather than weakening the constraint.
_SYSTEM_USER_ID = "system"
_SYSTEM_USER_EMAIL = "system@meridian.local"


@dataclass
class LoadedTree:
    """In-memory view of a `trees` row, ready for the graph builder."""

    tree_id: str
    graph_id: str | None
    last_commit_sha: str | None
    tree_data: dict[str, Any]


def load_tree(tree_id: str) -> LoadedTree:
    """Fetch a `READY` parse tree by `tree_id`.

    The status filter is part of the WHERE clause — C8 should never see a
    tree that's still building or errored, so they're invisible at the query
    layer rather than fetched-then-rejected.
    """
    stmt = select(Tree).where(
        Tree.tree_id == tree_id,
        Tree.status == TreeStatus.READY.value,
    )
    with get_session() as session:
        tree = session.execute(stmt).scalar_one_or_none()
        if tree is None:
            raise ValueError(f"tree not found or not ready: tree_id={tree_id}")
        if tree.tree_data is None:
            raise ValueError(f"tree has no payload: tree_id={tree_id}")

        loaded = LoadedTree(
            tree_id=tree.tree_id,
            graph_id=tree.graph_id,
            last_commit_sha=tree.last_commit_sha,
            tree_data=tree.tree_data,
        )

    logger.info(
        "db_utils: loaded tree %s (graph_id=%s nodes=%d edges=%d)",
        loaded.tree_id,
        loaded.graph_id,
        len(loaded.tree_data.get("nodes", [])),
        len(loaded.tree_data.get("edges", [])),
    )
    return loaded


def persist_graph(
    graph: nx.MultiDiGraph,
    *,
    repo_url: str,
    branch: str,
    repo_clone_id: str | None,
    last_commit_sha: str | None,
    user_id: str | None = None,
) -> str:
    """Insert a new `graphs` row carrying the C8 graph payload.

    Status stays `building` because Leiden (C9) hasn't run — `community` is
    not yet on the nodes and `community_count` is 0. C9 will mutate this row
    in place and flip status to `ready` per CLAUDE.md.

    Returns the new `graph_id`.
    """
    graph_id = str(uuid.uuid4())
    owner_id = user_id or _SYSTEM_USER_ID

    payload: dict[str, Any] = {
        "nodes": [
            {"id": node_id, **attrs} for node_id, attrs in graph.nodes(data=True)
        ],
        "edges": [
            {"source": u, "target": v, **attrs}
            for u, v, attrs in graph.edges(data=True)
        ],
    }

    with get_session() as session:
        if user_id is None:
            _ensure_system_user(session)
        session.add(
            Graph(
                graph_id=graph_id,
                user_id=owner_id,
                repo_clone_id=repo_clone_id,
                repo_url=repo_url,
                branch=branch,
                last_commit_sha=last_commit_sha,
                graph_data=payload,
                status=GraphStatus.BUILDING.value,
                node_count=graph.number_of_nodes(),
                edge_count=graph.number_of_edges(),
                community_count=0,
            )
        )
        session.commit()

    logger.info(
        "db_utils: persisted graph %s (user=%s repo=%s nodes=%d edges=%d status=building)",
        graph_id,
        owner_id,
        repo_url,
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )
    return graph_id


def _ensure_system_user(session) -> None:
    """Insert the placeholder system user once if missing.

    Idempotent — checks PK before inserting. Removed when auth lands.
    """
    existing = session.execute(
        select(User.user_id).where(User.user_id == _SYSTEM_USER_ID)
    ).first()
    if existing is not None:
        return
    session.add(
        User(
            user_id=_SYSTEM_USER_ID,
            email=_SYSTEM_USER_EMAIL,
            display_name="System (placeholder)",
            password="!disabled",  # not a hash; this user can't log in
            role="admin",
        )
    )
    session.flush()
    logger.info("db_utils: bootstrapped system user (placeholder until auth lands)")
