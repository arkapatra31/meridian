from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class SubmitRepoRequest(BaseModel):
    """Body for `POST /repos` — submit a GitHub repo for graph building."""

    url: HttpUrl = Field(..., description="GitHub repository URL")
    branch: str | None = Field(
        default=None, description="Optional branch (defaults to repo default)"
    )


class SubmitRepoResponse(BaseModel):
    repo_id: str = Field(..., description="Stable identifier derived from the repo URL")
    owner: str
    repo: str
    branch: str | None
    metadata: dict[str, Any]


class GetFileRequest(BaseModel):
    """Body for `POST /repos/file` — fetch a single file from a GitHub repo."""

    url: HttpUrl = Field(..., description="GitHub repository URL")
    path: str = Field(..., min_length=1, description="Path of the file inside the repo")
    branch: str | None = Field(
        default=None, description="Optional branch (defaults to repo default)"
    )


class GetFileResponse(BaseModel):
    repo_id: str
    owner: str
    repo: str
    branch: str | None
    path: str
    size: int = Field(..., description="Length of the decoded content in bytes")
    content: str = Field(..., description="UTF-8 decoded file contents")


class HealthResponse(BaseModel):
    status: str = "ok"
