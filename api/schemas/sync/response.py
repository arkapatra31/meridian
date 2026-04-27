from typing import Literal

from pydantic import BaseModel, Field


class DiffSummaryPayload(BaseModel):
    """Per-build summary emitted by C7 (the diff engine)."""

    mode: Literal["FULL", "PATCH"]
    nodes_added: int = 0
    nodes_removed: int = 0
    edges_added: int = 0
    edges_removed: int = 0
    ambiguous_added: int = 0
    ambiguous_removed: int = 0
    errors: list[str] = Field(default_factory=list)


class SyncResponse(BaseModel):
    """Result of `POST /repos/sync`.

    `mode` is the dispatch marker chosen by the ingestion layer:
      - `FULL` — no active graph existed, repo was freshly cloned
      - `PATCH` — active graph existed, incremental sync ran
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
    diff: DiffSummaryPayload | None = Field(
        default=None,
        description="C7 diff summary — populated for FULL mode today, PATCH later",
    )
