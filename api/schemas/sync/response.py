from typing import Literal

from pydantic import BaseModel, Field


class SyncResponse(BaseModel):
    """Result of `POST /repos/sync`.

    `mode` is the dispatch marker chosen by the ingestion layer:
      - `FULL` — no active graph existed, repo was freshly cloned and the
        parse tree was indexed.
      - `PATCH` — active graph existed, incremental sync ran.
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
    node_count: int = 0
    edge_count: int = 0
    ambiguous_count: int = 0
    errors: list[str] = Field(default_factory=list)
