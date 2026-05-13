"""Graph-resource routes — `GET /repos` (list), `GET /graph` (fetch by id),
`DELETE /repos/{graph_id}` (evict), `WS /playground/{graph_id}` (C6 QnA).

Lives in its own module so the build/sync surface (repos.py) and the read
surface evolve independently.
"""

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, WebSocket, status
from sqlalchemy import select, text

from db.database import get_session
from db.entities import Graph
from db.entities.repo_clone import RepoClone
from orchestrator.qna_chat import run_playground_session

from ..deps import get_current_user_id
from ..schemas.graph import GraphResponse, GraphSummary

router = APIRouter(tags=["graphs"])


@router.get(
    "/repos",
    response_model=list[GraphSummary],
    summary="List all graphs owned by the authenticated user",
)
async def list_graphs(
    user_id: str = Depends(get_current_user_id),
) -> list[GraphSummary]:
    """Return graph metadata (no nodes/edges) for every graph the caller owns,
    ordered newest-updated first.
    """
    stmt = (
        select(Graph)
        .where(Graph.user_id == user_id)
        .order_by(Graph.updated_at.desc())
    )
    with get_session() as session:
        rows = session.execute(stmt).scalars().all()
        return [
            GraphSummary(
                graph_id=row.graph_id,
                repo_url=row.repo_url,
                branch=row.branch,
                status=row.status,
                node_count=row.node_count,
                edge_count=row.edge_count,
                community_count=row.community_count,
                created_at=row.created_at,
                updated_at=row.updated_at,
                last_synced_at=row.last_synced_at,
            )
            for row in rows
        ]


@router.get(
    "/graph",
    response_model=GraphResponse,
    summary="Fetch the persisted graph payload by graph_id",
)
async def get_graph(
    graph_id: str = Query(..., description="UUID of the graph to fetch"),
    user_id: str = Depends(get_current_user_id),
) -> GraphResponse:
    """Return the full graph (nodes + edges + Leiden enrichment) by ID.

    Reads `graphs.graph_data` directly — no deserialization through NetworkX.
    Returns 404 if the row is missing, not owned by the caller, or has no payload.
    """
    stmt = select(Graph).where(
        Graph.graph_id == graph_id,
        Graph.user_id == user_id,
    )
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


@router.delete(
    "/repos/{graph_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Evict graph: delete graph, tree, clone record and disk cache. Sync run history is preserved.",
)
async def evict_graph(
    graph_id: str,
    user_id: str = Depends(get_current_user_id),
) -> None:
    """Permanently removes the graph, its parse tree, graph history snapshots,
    and the repo clone record (plus on-disk cache directory).  Sync run rows
    are intentionally left in place as a historical audit trail — they become
    orphaned rows with a dangling graph_id FK, which is acceptable for SQLite.
    """
    with get_session() as session:
        row = session.execute(
            select(Graph).where(Graph.graph_id == graph_id, Graph.user_id == user_id)
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"graph not found: {graph_id}"
            )

        clone_path: Path | None = None
        if row.repo_clone_id:
            clone_row = session.execute(
                select(RepoClone).where(RepoClone.repo_id == row.repo_clone_id)
            ).scalar_one_or_none()
            if clone_row:
                clone_path = Path(clone_row.path)

        # Disable FK enforcement so sync_runs are orphaned rather than cascade-deleted.
        session.execute(text("PRAGMA foreign_keys = OFF"))
        session.execute(text("DELETE FROM trees WHERE graph_id = :g"), {"g": graph_id})
        session.execute(text("DELETE FROM graph_history WHERE graph_id = :g"), {"g": graph_id})
        session.execute(text("DELETE FROM graphs WHERE graph_id = :g"), {"g": graph_id})
        if row.repo_clone_id:
            session.execute(
                text("DELETE FROM repo_clones WHERE repo_id = :r"),
                {"r": row.repo_clone_id},
            )
        session.execute(text("PRAGMA foreign_keys = ON"))
        session.commit()

    if clone_path and clone_path.exists():
        shutil.rmtree(clone_path, ignore_errors=True)


@router.get(
    "/graph/{graph_id}/skill",
    summary="Download an AI-tool context file for this graph",
    response_class=Response,
)
async def download_skill_file(
    graph_id: str,
    tool: str = Query(
        "claude_code",
        description="Target tool: claude_code | cursor | copilot | windsurf",
    ),
    user_id: str = Depends(get_current_user_id),
) -> Response:
    """Generate and return a downloadable context file for the requested AI coding tool.

    - ``claude_code`` → ``.claude/commands/<slug>.md`` (slash command, frontmatter)
    - ``cursor``      → ``.cursor/rules/<slug>-context.mdc`` (MDC frontmatter)
    - ``copilot``     → ``.github/copilot-instructions.md`` (plain markdown, always-on)
    - ``windsurf``    → ``.windsurfrules`` (plain markdown, always-on)

    Requires the graph to be in READY status.
    """
    from playground.skill_generator import (
        SUPPORTED_TOOLS,
        generate_skill_file,
        skill_filename,
    )

    if tool not in SUPPORTED_TOOLS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unsupported tool '{tool}'. Choose from: {sorted(SUPPORTED_TOOLS)}",
        )

    stmt = select(Graph).where(Graph.graph_id == graph_id, Graph.user_id == user_id)
    with get_session() as session:
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"graph not found: {graph_id}")
        if row.status != "READY" or row.graph_data is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"graph {graph_id} is not READY (status={row.status})",
            )
        content = generate_skill_file(
            row.graph_data,
            repo_url=row.repo_url,
            branch=row.branch,
            graph_id=graph_id,
            last_commit_sha=row.last_commit_sha,
            tool=tool,
        )
        filename = skill_filename(row.repo_url, tool=tool)

    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.websocket("/playground/{graph_id}")
async def playground_ws(
    websocket: WebSocket,
    graph_id: str,
    token: str = Query(..., description="JWT (browsers can't set headers on WS)"),
    query: str | None = Query(None, description="Optional initial question"),
) -> None:
    """Multi-turn streaming QnA over a graph. Service logic lives in
    `orchestrator.qna_chat.run_playground_session`.
    """
    await run_playground_session(
        websocket,
        graph_id,
        token=token,
        initial_query=query,
    )
