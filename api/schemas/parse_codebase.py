from typing import Any

from pydantic import BaseModel, Field


class ParseCodebaseRequest(BaseModel):
    """Body for `POST /repos/parse-codebase` — Pass 1 tree-sitter extraction."""

    repo: str = Field(
        ...,
        description="Repo directory name under <CACHE_ROOT>/codebase/ (as cloned by /repos/index-repo)",
    )
    include_graph: bool = Field(
        default=False,
        description="If true, return full nodes/edges/ambiguous lists. Default false returns counts only.",
    )


class ParseCodebaseResponse(BaseModel):
    repo: str
    root: str
    files_parsed: int
    files_skipped: int
    node_count: int
    edge_count: int
    ambiguous_count: int
    languages: dict[str, int]
    errors: list[str] = Field(default_factory=list)
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None
    ambiguous: list[dict[str, Any]] | None = None
