from datetime import datetime
from enum import Enum

from typing import Any

from sqlalchemy import JSON, TIMESTAMP, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class GraphStatus(str, Enum):
    ACTIVE = "Active"
    BUILDING = "Building"
    INACTIVE = "Inactive"
    ERROR = "Error"


class Graph(Base):
    __tablename__ = "graphs"

    graph_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.user_id"), nullable=False, index=True
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

    user: Mapped["User"] = relationship("User", back_populates="graphs")  # noqa: F821
