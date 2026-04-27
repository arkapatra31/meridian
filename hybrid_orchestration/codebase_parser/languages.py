"""File-extension → tree-sitter language mapping.

Names match the language identifiers used by `tree-sitter-language-pack`.
"""

from __future__ import annotations

from pathlib import Path

EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sc": "scala",
    ".php": "php",
    ".swift": "swift",
    ".lua": "lua",
    ".zig": "zig",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".vue": "vue",
    ".svelte": "svelte",
}


def detect_language(path: Path) -> str | None:
    return EXT_TO_LANG.get(path.suffix.lower())
