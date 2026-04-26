from dataclasses import asdict

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from hybrid_orchestration.codebase_parser import parse_codebase
from hybrid_orchestration.surgical_agent import resolve_ambiguous
from ingestion_layer.repo_cache.clone_repo import CloneError, clone_repo

from ..schemas import (
    IndexRepoRequest,
    IndexRepoResponse,
    ParseCodebaseRequest,
    ParseCodebaseResponse,
)

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


@router.post(
    "/parse-codebase",
    response_model=ParseCodebaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Pass 1: tree-sitter extraction over a cloned repo",
)
async def parse_codebase_endpoint(body: ParseCodebaseRequest) -> ParseCodebaseResponse:
    try:
        # Pass 1: tree-sitter (CPU-bound) — run off the event loop.
        result = await run_in_threadpool(parse_codebase, body.repo)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Pass 2: surgical Agent SDK — resolves AmbiguousRefs into INFERRED edges.
    result = await resolve_ambiguous(result)

    return ParseCodebaseResponse(
        repo=result.repo,
        root=result.root,
        files_parsed=result.files_parsed,
        files_skipped=result.files_skipped,
        node_count=len(result.nodes),
        edge_count=len(result.edges),
        ambiguous_count=len(result.ambiguous),
        languages=result.languages,
        errors=result.errors,
        nodes=[asdict(n) for n in result.nodes] if body.include_graph else None,
        edges=[asdict(e) for e in result.edges] if body.include_graph else None,
        ambiguous=[asdict(a) for a in result.ambiguous] if body.include_graph else None,
    )
