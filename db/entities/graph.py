from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class GraphStatus(str, Enum):
    BUILDING = "BUILDING"
    READY = "READY"
    ERROR = "ERROR"


class Graph(Base):
    __tablename__ = "graphs"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "repo_url", "branch", name="uq_graphs_user_repo_branch"
        ),
    )

    graph_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.user_id"), nullable=False, index=True
    )
    repo_clone_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("repo_clones.repo_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    repo_url: Mapped[str] = mapped_column(String, nullable=False, index=True)
    branch: Mapped[str] = mapped_column(String, nullable=False, default="main")
    last_commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    graph_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=GraphStatus.BUILDING.value
    )
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    community_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="graphs")  # noqa: F821
    repo_clone: Mapped["RepoClone | None"] = relationship(  # noqa: F821
        "RepoClone", back_populates="graphs", foreign_keys=[repo_clone_id]
    )
    sync_runs: Mapped[list["SyncRun"]] = relationship(  # noqa: F821
        "SyncRun", back_populates="graph", cascade="all, delete-orphan"
    )
    tree: Mapped["Tree | None"] = relationship(  # noqa: F821
        "Tree", back_populates="graph", uselist=False, cascade="all, delete-orphan"
    )
    history: Mapped[list["GraphHistory"]] = relationship(  # noqa: F821
        "GraphHistory",
        back_populates="graph",
        cascade="all, delete-orphan",
        order_by="GraphHistory.version",
    )
