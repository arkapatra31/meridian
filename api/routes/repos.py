from fastapi import APIRouter, Depends, Header, HTTPException, status

from orchestrator.orchestrator import sync_repo
from ingestion_layer.repo_cache.clone_repo import CloneError

from ..deps import get_current_user_id
from ..schemas import SyncRequest, SyncResponse

router = APIRouter(prefix="/repos", tags=["repos"])


@router.post(
    "/sync",
    response_model=SyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Dispatch FULL clone or PATCH update based on DB state",
)
async def sync(
    body: SyncRequest,
    x_github_pat: str = Header(
        ...,
        alias="X-GitHub-PAT",
        description="GitHub Personal Access Token (passed per-request, never stored)",
    ),
    user_id: str = Depends(get_current_user_id),
) -> SyncResponse:
    url = str(body.url)

    try:
        result = await sync_repo(
            repo_url=url,
            pat=x_github_pat,
            branch=body.branch,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except CloneError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    clone = result.clone
    tree = result.tree

    return SyncResponse(
        repo_url=result.repo_url,
        branch=result.branch,
        mode=result.mode,
        repo_id=clone.repo_id if clone else None,
        owner=clone.owner if clone else None,
        repo=clone.repo if clone else None,
        path=str(clone.path) if clone else None,
        tree_id=result.tree_id,
        graph_id=result.graph_id,
        errors=list(tree.errors) if tree else [],
    )
