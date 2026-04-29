from datetime import datetime

from pydantic import BaseModel


class RegisterResponse(BaseModel):
    user_id: str
    email: str
    display_name: str
    github_username: str | None
    role: str
    created_at: datetime


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    display_name: str
