from pydantic import BaseModel, Field, HttpUrl


class IndexRepoRequest(BaseModel):
    """Body for `POST /repos/index-repo` — clone a GitHub repo into the local cache."""

    url: HttpUrl = Field(..., description="GitHub repository URL")
    branch: str | None = Field(
        default=None, description="Optional branch (defaults to repo default)"
    )
