from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class RepoClone(Base):
    __tablename__ = "repo_clones"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "owner", "repo", "branch", name="uq_repo_clone_user_repo_branch"
        ),
    )

    repo_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owner: Mapped[str] = mapped_column(String, nullable=False)
    repo: Mapped[str] = mapped_column(String, nullable=False)
    repo_url: Mapped[str] = mapped_column(String, nullable=False)
    branch: Mapped[str | None] = mapped_column(String, nullable=True)
    path: Mapped[str] = mapped_column(String, nullable=False)
    last_commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cloned_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.current_timestamp()
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    evicted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)

    user: Mapped["User | None"] = relationship(  # noqa: F821
        "User", back_populates="repo_clones"
    )
    graphs: Mapped[list["Graph"]] = relationship(  # noqa: F821
        "Graph", back_populates="repo_clone"
    )
