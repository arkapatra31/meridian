from dataclasses import asdict

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from hybrid_orchestration.codebase_parser import parse_codebase
from hybrid_orchestration.surgical_agent import resolve_ambiguous
from ingestion_layer.repo_actions import sync_repo
from ingestion_layer.repo_cache.clone_repo import CloneError, clone_repo

from ..schemas import (
    IndexRepoRequest,
    IndexRepoResponse,
    ParseCodebaseRequest,
    ParseCodebaseResponse,
    SyncRequest,
    SyncResponse,
)
from ..schemas.sync import DiffSummaryPayload

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
    )


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
) -> SyncResponse:
    url = str(body.url)

    try:
        result = await sync_repo(
            repo_url=url,
            pat=x_github_pat,
            branch=body.branch,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except CloneError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    clone = result.clone
    diff_payload: DiffSummaryPayload | None = None
    if result.diff is not None:
        s = result.diff.summary
        diff_payload = DiffSummaryPayload(
            mode=s.mode,
            nodes_added=s.nodes_added,
            nodes_removed=s.nodes_removed,
            edges_added=s.edges_added,
            edges_removed=s.edges_removed,
            ambiguous_added=s.ambiguous_added,
            ambiguous_removed=s.ambiguous_removed,
            errors=s.errors,
        )

    return SyncResponse(
        repo_url=result.repo_url,
        branch=result.branch,
        mode=result.mode,
        repo_id=clone.repo_id if clone else None,
        owner=clone.owner if clone else None,
        repo=clone.repo if clone else None,
        path=str(clone.path) if clone else None,
        diff=diff_payload,
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
