"""Per-language tree-sitter walkers.

Each walker turns a parsed source file into (nodes, edges, ambiguous-refs)
following the shared schema in `..models`. Add a new language by writing a
walker module here and registering it in `..parser.WALKERS`.
"""

from .java import parse_java
from .javascript import parse_javascript, parse_tsx, parse_typescript
from .python import parse_python

__all__ = ["parse_java", "parse_javascript", "parse_tsx", "parse_typescript", "parse_python"]
