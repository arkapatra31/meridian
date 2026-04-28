"""Database queries used by the graph engine (C5a/C5b/C8)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import networkx as nx
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

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


@dataclass
class LoadedGraph:
    """In-memory view of a `graphs` row, ready for Leiden (C5b)."""

    graph_id: str
    graph: nx.MultiDiGraph
    repo_url: str
    branch: str
    last_commit_sha: str | None
    status: str


def load_tree(tree_id: str) -> LoadedTree:
    """Fetch a `READY` parse tree by `tree_id`.

    The status filter is part of the WHERE clause — C5a should never see a
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
    """Upsert the `graphs` row carrying the C5a graph payload.

    `(user_id, repo_url, branch)` identifies a graph from the user's
    perspective — a re-build for the same triple must not create a parallel
    row. We use SQLite's `INSERT ... ON CONFLICT DO UPDATE` against the
    `uq_graphs_user_repo_branch` constraint: existing rows are reset back
    to `BUILDING` with the fresh payload (community data cleared so C5b can
    rewrite it in place); new rows get a fresh UUID.
    """
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
    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()
    new_graph_id = str(uuid.uuid4())

    stmt = sqlite_insert(Graph).values(
        graph_id=new_graph_id,
        user_id=owner_id,
        repo_clone_id=repo_clone_id,
        repo_url=repo_url,
        branch=branch,
        last_commit_sha=last_commit_sha,
        graph_data=payload,
        status=GraphStatus.BUILDING.value,
        node_count=node_count,
        edge_count=edge_count,
        community_count=0,
    )
    upsert = stmt.on_conflict_do_update(
        index_elements=["user_id", "repo_url", "branch"],
        set_={
            "repo_clone_id": stmt.excluded.repo_clone_id,
            "last_commit_sha": stmt.excluded.last_commit_sha,
            "graph_data": stmt.excluded.graph_data,
            "status": stmt.excluded.status,
            "node_count": stmt.excluded.node_count,
            "edge_count": stmt.excluded.edge_count,
            "community_count": stmt.excluded.community_count,
            "error_message": None,
            "updated_at": func.current_timestamp(),
        },
    ).returning(Graph.graph_id)

    with get_session() as session:
        if user_id is None:
            _ensure_system_user(session)
        graph_id = session.execute(upsert).scalar_one()
        session.commit()

    logger.info(
        "db_utils: upserted graph %s (user=%s repo=%s nodes=%d edges=%d status=BUILDING)",
        graph_id,
        owner_id,
        repo_url,
        node_count,
        edge_count,
    )
    return graph_id


def load_graph(graph_id: str) -> LoadedGraph:
    """Fetch a `graphs` row and rehydrate its `MultiDiGraph` payload.

    No status filter: C5b picks up a `building` graph that C5a just wrote and
    PATCH re-cluster picks up a row that briefly flips back to `building`.
    Callers (the orchestrator) decide *when* to call this; the query layer
    just returns whatever's there.
    """
    stmt = select(Graph).where(Graph.graph_id == graph_id)
    with get_session() as session:
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            raise ValueError(f"graph not found: graph_id={graph_id}")
        if row.graph_data is None:
            raise ValueError(f"graph has no payload: graph_id={graph_id}")

        payload = row.graph_data
        g: nx.MultiDiGraph = nx.MultiDiGraph()
        g.graph["graph_id"] = row.graph_id
        g.graph["repo_url"] = row.repo_url
        g.graph["branch"] = row.branch
        g.graph["last_commit_sha"] = row.last_commit_sha

        for node in payload.get("nodes", []) or []:
            node_id = node["id"]
            attrs = {k: v for k, v in node.items() if k != "id"}
            g.add_node(node_id, **attrs)

        for edge in payload.get("edges", []) or []:
            attrs = {
                k: v for k, v in edge.items() if k not in ("source", "target")
            }
            g.add_edge(edge["source"], edge["target"], **attrs)

        loaded = LoadedGraph(
            graph_id=row.graph_id,
            graph=g,
            repo_url=row.repo_url,
            branch=row.branch,
            last_commit_sha=row.last_commit_sha,
            status=row.status,
        )

    logger.info(
        "db_utils: loaded graph %s (nodes=%d edges=%d status=%s)",
        loaded.graph_id,
        g.number_of_nodes(),
        g.number_of_edges(),
        loaded.status,
    )
    return loaded


def link_tree_to_graph(tree_id: str, graph_id: str) -> None:
    """Link a `trees` row to its `graphs` row (1:1 via the UNIQUE FK).

    Called by the orchestrator after C5b finishes — the parse tree is final,
    the graph is `READY`, now we tie them together. On a re-build an older
    tree may still point at this `graph_id` from a previous run; we drop it
    first because `trees.graph_id` is UNIQUE and can't host both.
    """
    with get_session() as session:
        stale = (
            session.execute(
                select(Tree).where(
                    Tree.graph_id == graph_id,
                    Tree.tree_id != tree_id,
                )
            )
            .scalars()
            .all()
        )
        stale_count = len(stale)
        for t in stale:
            session.delete(t)
        if stale_count:
            session.flush()

        new_tree = session.get(Tree, tree_id)
        if new_tree is None:
            raise ValueError(f"tree not found: tree_id={tree_id}")
        new_tree.graph_id = graph_id
        session.commit()

    logger.info(
        "db_utils: linked tree %s → graph %s (dropped %d stale)",
        tree_id,
        graph_id,
        stale_count,
    )


def update_graph_with_clusters(
    graph_id: str,
    *,
    graph: nx.MultiDiGraph,
    community_count: int,
) -> None:
    """UPDATE the `graphs` row in place after C5b finishes.

    Mutates `graph_data` (nodes now carry `community` plus god/orphan flags),
    sets `community_count`, and flips `status` → `ready`. `node_count` /
    `edge_count` are untouched: Leiden enriches topology, never changes it.
    """
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
        row = session.execute(
            select(Graph).where(Graph.graph_id == graph_id)
        ).scalar_one_or_none()
        if row is None:
            raise ValueError(f"graph not found: graph_id={graph_id}")
        row.graph_data = payload
        row.community_count = community_count
        row.status = GraphStatus.READY.value
        session.commit()

    logger.info(
        "db_utils: graph %s clustered → status=ready communities=%d",
        graph_id,
        community_count,
    )


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
