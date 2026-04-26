from pydantic import BaseModel, Field


class IndexRepoResponse(BaseModel):
    repo_id: str
    owner: str
    repo: str
    branch: str | None
    reused: bool = Field(
        ..., description="True if an existing clone was reused (no fresh clone happened)"
    )
