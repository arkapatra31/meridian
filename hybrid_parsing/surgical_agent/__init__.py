"""C4b — Pass 2 surgical agent.

Resolves AmbiguousRef instances from Pass 1 into INFERRED edges using the
Claude Agent SDK with Read/Glob/Grep on the cloned repo.
"""

from .resolver import resolve_ambiguous

__all__ = ["resolve_ambiguous"]
