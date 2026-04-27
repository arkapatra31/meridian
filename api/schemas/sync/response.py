from typing import Literal

from pydantic import BaseModel, Field


class SyncResponse(BaseModel):
    """Result of `POST /repos/sync`.

    `mode` is the dispatch marker chosen by the orchestrator (C4):
      - `FULL` — no active graph existed, repo was freshly cloned, the parse
        tree was indexed, and C8 persisted a `graphs` row.
      - `PATCH` — active graph existed, incremental sync ran.

    Counts are intentionally omitted — clients fetch the graph payload via
    `GET /repos/{graph_id}/graph` (or the parse tree via `tree_id`) when they
    need detail.
    """

    repo_url: str
    branch: str
    mode: Literal["FULL", "PATCH"]
    repo_id: str | None = Field(
        default=None,
        description="Populated when mode == FULL (from the fresh clone)",
    )
    owner: str | None = None
    repo: str | None = None
    path: str | None = Field(
        default=None, description="On-disk cache path of the clone (FULL only)"
    )
    tree_id: str | None = Field(
        default=None,
        description="ID of the indexed parse tree — fetch via the trees endpoint",
    )
    graph_id: str | None = Field(
        default=None,
        description="ID of the persisted graph (status='building' until C9 runs)",
    )
    errors: list[str] = Field(default_factory=list)
