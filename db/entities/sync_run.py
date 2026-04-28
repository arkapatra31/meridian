from datetime import datetime
from enum import Enum

from sqlalchemy import TIMESTAMP, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class SyncMode(str, Enum):
    FULL = "FULL"
    PATCH = "PATCH"


class SyncRunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class SyncRun(Base):
    __tablename__ = "sync_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    graph_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("graphs.graph_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=SyncRunStatus.RUNNING.value
    )
    previous_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    current_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    nodes_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nodes_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edges_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edges_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ambiguous_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ambiguous_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.current_timestamp()
    )
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)

    graph: Mapped["Graph"] = relationship("Graph", back_populates="sync_runs")  # noqa: F821
