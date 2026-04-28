from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class GraphResponse(BaseModel):
    """Result of `GET /repos/{graph_id}/graph` — full graph payload for the FE.

    `nodes` and `edges` are the C5a-built + C5b-clustered graph payload,
    JSON-serialized (no NetworkX object — just the same shape we persist).
    Each node carries Leiden enrichment (`community`, `is_god`, `is_orphan`)
    when status='READY'; on a `BUILDING` row those keys may be missing.
    """

    graph_id: str
    repo_url: str
    branch: str
    status: Literal["BUILDING", "READY", "ERROR"]
    last_commit_sha: str | None = None
    node_count: int
    edge_count: int
    community_count: int
    error_message: str | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    last_synced_at: datetime | None = None
