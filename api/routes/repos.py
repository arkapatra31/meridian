from fastapi import APIRouter, Header, HTTPException, status

from ingestion_layer.github_mcp import GithubMCPClient, GithubMCPError
from ingestion_layer.github_mcp.helpers import repo_id

from ..schemas import (
    GetFileRequest,
    GetFileResponse,
    SubmitRepoRequest,
    SubmitRepoResponse,
)

router = APIRouter(prefix="/repos", tags=["repos"])


@router.post(
    "",
    response_model=SubmitRepoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a GitHub repository for graph building",
)
async def submit_repo(
    body: SubmitRepoRequest,
    x_github_pat: str = Header(
        ...,
        alias="X-GitHub-PAT",
        description="GitHub Personal Access Token (passed per-request, never stored)",
    ),
) -> SubmitRepoResponse:
    url = str(body.url)

    try:
        client = GithubMCPClient(repo_url=url, pat=x_github_pat, branch=body.branch)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        async with client as gh:
            metadata = await gh.list_files()
    except Exception as exc:  # noqa: BLE001 — surface upstream failures cleanly
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch repo metadata via GitHub MCP: {exc}",
        ) from exc

    return SubmitRepoResponse(
        repo_id=repo_id(url),
        owner=client.owner,
        repo=client.repo,
        branch=body.branch,
        metadata=metadata if isinstance(metadata, dict) else {"raw": metadata},
    )


@router.post(
    "/file",
    response_model=GetFileResponse,
    summary="Fetch a single file's contents from a GitHub repository",
)
async def get_file(
    body: GetFileRequest,
    x_github_pat: str = Header(
        ...,
        alias="X-GitHub-PAT",
        description="GitHub Personal Access Token (passed per-request, never stored)",
    ),
) -> GetFileResponse:
    url = str(body.url)

    try:
        client = GithubMCPClient(repo_url=url, pat=x_github_pat, branch=body.branch)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        async with client as gh:
            content = await gh.get_file(body.path)
    except GithubMCPError as exc:
        # Tool-level failure (file not found, permission denied, etc.)
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface upstream failures cleanly
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch file via GitHub MCP: {exc}",
        ) from exc

    return GetFileResponse(
        repo_id=repo_id(url),
        owner=client.owner,
        repo=client.repo,
        branch=body.branch,
        path=body.path,
        size=len(content.encode("utf-8")),
        content=content,
    )
