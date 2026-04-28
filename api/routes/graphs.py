"""Graph-resource routes — currently just `GET /repos/{graph_id}/graph`.

Lives in its own module (rather than alongside `POST /repos/sync` in
`repos.py`) so the build/sync surface and the read surface evolve
independently — adding history, version diffs, or QnA later won't bloat
the sync handler.
"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from db.database import get_session
from db.entities import Graph

from ..schemas.graph import GraphResponse

router = APIRouter(tags=["graphs"])


@router.get(
    "/graph",
    response_model=GraphResponse,
    summary="Fetch the persisted graph payload by graph_id",
)
async def get_graph(graph_id: str = Query(..., description="UUID of the graph to fetch")) -> GraphResponse:
    """Return the full graph (nodes + edges + Leiden enrichment) by ID.

    Reads `graphs.graph_data` directly — no deserialization through
    NetworkX. The payload is whatever C5a wrote and C5b mutated in place.
    Returns 404 if the row is missing or has no payload yet.
    """
    stmt = select(Graph).where(Graph.graph_id == graph_id)
    with get_session() as session:
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"graph not found: {graph_id}",
            )
        if row.graph_data is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"graph {graph_id} has no payload (status={row.status})",
            )

        payload = row.graph_data
        return GraphResponse(
            graph_id=row.graph_id,
            repo_url=row.repo_url,
            branch=row.branch,
            status=row.status,
            last_commit_sha=row.last_commit_sha,
            node_count=row.node_count,
            edge_count=row.edge_count,
            community_count=row.community_count,
            error_message=row.error_message,
            nodes=payload.get("nodes", []),
            edges=payload.get("edges", []),
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_synced_at=row.last_synced_at,
        )
