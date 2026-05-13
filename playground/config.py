"""Env-driven config for the QnA agent."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class QnaConfig:
    """Tuning knobs for the QnA agent.

    top_k   — how many seed nodes search_nodes returns per turn.
    max_turns — max conversation rounds before the session is closed.
    """

    top_k: int = 6
    max_turns: int = 8

    @classmethod
    def default(cls) -> "QnaConfig":
        return cls(
            top_k=int(os.environ.get("QNA_TOP_K", "6")),
            max_turns=int(os.environ.get("QNA_MAX_TURNS", "8")),
        )
