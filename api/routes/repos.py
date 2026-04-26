from fastapi import APIRouter, Header, HTTPException, status

from ingestion_layer.repo_cache.clone_repo import CloneError, clone_repo

from ..schemas import IndexRepoRequest, IndexRepoResponse

router = APIRouter(prefix="/repos", tags=["repos"])


@router.post(
    "/index-repo",
    response_model=IndexRepoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Clone a GitHub repository into the local repo cache",
)
async def index_repo(
    body: IndexRepoRequest,
    x_github_pat: str = Header(
        ...,
        alias="X-GitHub-PAT",
        description="GitHub Personal Access Token (passed per-request, never stored)",
    ),
) -> IndexRepoResponse:
    url = str(body.url)

    try:
        result = await clone_repo(
            repo_url=url,
            pat=x_github_pat,
            branch=body.branch,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except CloneError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return IndexRepoResponse(
        repo_id=result.repo_id,
        owner=result.owner,
        repo=result.repo,
        branch=result.branch,
        reused=result.reused,
    )
