from pydantic import BaseModel


class IndexRepoResponse(BaseModel):
    repo_id: str
    owner: str
    repo: str
    branch: str | None
