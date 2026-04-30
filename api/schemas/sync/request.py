from pydantic import BaseModel, Field, HttpUrl


class SyncRequest(BaseModel):
    """Body for `POST /repos/sync` — dispatch FULL clone or PATCH update."""

    url: HttpUrl = Field(..., description="GitHub repository URL")
    branch: str = Field(..., description="Branch to clone/sync")
