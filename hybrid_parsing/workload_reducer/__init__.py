"""Pass 1.5 — Symbol-index workload reducer.

Sits between C4a (tree-sitter) and C4b (agent resolver).
Resolves or drops ambiguous refs that don't need an LLM.
"""

from .reducer import reduce_workload

__all__ = ["reduce_workload"]
