from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, TIMESTAMP, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class TreeStatus(str, Enum):
    BUILDING = "building"
    READY = "ready"
    ERROR = "error"


class Tree(Base):
    """Parse-tree artifact (C5 + C6 output) for a graph.

    One tree per graph. FULL builds insert the row; PATCH mutates it in
    place (drop nodes/edges from changed files, add re-parsed ones, fix
    cross-file edges) and feeds the updated tree to C8.
    """

    __tablename__ = "trees"

    tree_id: Mapped[str] = mapped_column(String, primary_key=True)
    graph_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("graphs.graph_id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
        index=True,
    )
    tree_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=TreeStatus.BUILDING.value
    )
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ambiguous_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    graph: Mapped["Graph"] = relationship("Graph", back_populates="tree")  # noqa: F821
