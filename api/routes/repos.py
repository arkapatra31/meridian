import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status

from graph_engine.utils.db_utils import mark_graph_error, reserve_graph
from orchestrator.orchestrator import sync_repo
from orchestrator.utils.db_utils import get_active_graph

from ..deps import get_current_user_id
from ..schemas import SyncRequest, SyncResponse

logger = logging.getLogger("meridian.api.repos")

router = APIRouter(prefix="/repos", tags=["repos"])


async def _run_sync(
    repo_url: str,
    pat: str,
    branch: str,
    user_id: str,
) -> None:
    """Background worker: run the full pipeline and mark ERROR on failure."""
    try:
        await sync_repo(repo_url=repo_url, pat=pat, branch=branch, user_id=user_id)
    except Exception as exc:
        logger.exception(
            "sync background task failed for %s@%s", repo_url, branch
        )
        await asyncio.to_thread(
            mark_graph_error,
            repo_url=repo_url,
            branch=branch,
            user_id=user_id,
            error_message=str(exc),
        )


@router.post(
    "/sync",
    response_model=SyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Dispatch FULL clone or PATCH update; returns 202 immediately",
)
async def sync(
    body: SyncRequest,
    background_tasks: BackgroundTasks,
    x_github_pat: str = Header(
        ...,
        alias="X-GitHub-PAT",
        description="GitHub Personal Access Token (passed per-request, never stored)",
    ),
    user_id: str = Depends(get_current_user_id),
) -> SyncResponse:
    url = str(body.url)
    branch = body.branch or "main"

    # Pre-flight: determine mode and secure a graph_id before dispatching.
    # Both are lightweight DB reads — push off the event loop.
    active = await asyncio.to_thread(get_active_graph, url, branch, user_id)

    if active is not None:
        graph_id: str = active.graph_id
        mode = "PATCH"
    else:
        try:
            graph_id = await asyncio.to_thread(reserve_graph, url, branch, user_id)
        except Exception as exc:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            ) from exc
        mode = "FULL"

    background_tasks.add_task(
        _run_sync,
        repo_url=url,
        pat=x_github_pat,
        branch=branch,
        user_id=user_id,
    )

    return SyncResponse(
        repo_url=url,
        branch=branch,
        mode=mode,
        graph_id=graph_id,
    )
