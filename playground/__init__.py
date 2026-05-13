"""C6 — QnA Agent.

Multi-turn, streaming Q&A over a persisted code knowledge graph.
Each turn injects a BFS-extracted subgraph slice as context for the model.
"""

from .session import QnaSession
from .config import QnaConfig

__all__ = ["QnaSession", "QnaConfig"]
