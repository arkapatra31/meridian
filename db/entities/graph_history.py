from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class GraphHistory(Base):
    """Immutable snapshot of a successful graph build (FULL or PATCH).

    One row is written per (graph_id, version) at the moment C5b flips the
    live `graphs` row to READY — i.e. only successful versions land here,
    never half-built or errored ones, and never no-op PATCHes (where
    graph_data didn't actually change).

    The link to `sync_runs` carries the why-it-changed metadata (mode,
    previous_sha, current_sha, deltas), so this row stays lean and
    deduplicates nothing.
    """

    __tablename__ = "graph_history"
    __table_args__ = (
        UniqueConstraint("graph_id", "version", name="uq_graph_history_version"),
    )

    history_id: Mapped[str] = mapped_column(String, primary_key=True)
    graph_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("graphs.graph_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("sync_runs.run_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    graph_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    community_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.current_timestamp()
    )

    graph: Mapped["Graph"] = relationship(  # noqa: F821
        "Graph", back_populates="history"
    )
