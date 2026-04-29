from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    github_username: str | None = Field(default=None, max_length=39)

    @field_validator("email")
    @classmethod
    def block_system_email(cls, v: str) -> str:
        if v.lower() == "system@meridian.local":
            raise ValueError("reserved email address")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)
