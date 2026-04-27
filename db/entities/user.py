from datetime import datetime

from sqlalchemy import TIMESTAMP, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    github_username: Mapped[str | None] = mapped_column(String, nullable=True)
    password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)

    graphs: Mapped[list["Graph"]] = relationship(  # noqa: F821
        "Graph", back_populates="user", cascade="all, delete-orphan"
    )
    repo_clones: Mapped[list["RepoClone"]] = relationship(  # noqa: F821
        "RepoClone", back_populates="user", cascade="all, delete-orphan"
    )
