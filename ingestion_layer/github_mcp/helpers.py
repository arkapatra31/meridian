"""Pure helpers for the GitHub MCP client.

Kept free of any class state so they're trivially testable and reusable.
"""

import hashlib
import os
import re

DEFAULT_REMOTE_URL = "https://api.githubcopilot.com/mcp/"

# Scheme-agnostic: matches http://, https://, git@ (SSH), and bare github.com URLs.
# Tolerates trailing path segments (/tree/<branch>, /blob/..., /pull/N), query
# strings, and fragments — users often paste browser URLs.
_GITHUB_URL_RE = re.compile(
    r"github\.com[:/]+(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?(?:[/?#]|$)"
)


def parse_owner_repo(url: str) -> tuple[str, str]:
    """Extract (owner, repo) from any GitHub URL.

    Accepts:
      - https://github.com/foo/bar
      - http://github.com/foo/bar
      - https://github.com/foo/bar.git
      - https://github.com/foo/bar/tree/<branch>
      - https://github.com/foo/bar/blob/<sha>/path/to/file
      - git@github.com:foo/bar.git
    """
    m = _GITHUB_URL_RE.search(url.strip())
    if not m:
        raise ValueError(f"Not a GitHub repository URL: {url}")
    return m.group("owner"), m.group("repo")


def repo_id(url: str) -> str:
    """Stable 16-char identifier for a repo URL — used for cache paths and API IDs.

    Canonicalizes to `github.com/<owner>/<repo>` (lowercased) so a clone URL
    (https/http/SSH) and a web URL pointing at the same repo hash to the same ID.
    """
    owner, repo = parse_owner_repo(url)
    canonical = f"github.com/{owner.lower()}/{repo.lower()}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def build_mcp_endpoint(
    pat: str,
    toolsets: str | None = None,
    readonly: bool = False,
) -> tuple[str, dict[str, str]]:
    """Return (url, headers) for the hosted GitHub MCP server.

    Honors env overrides:
      - GITHUB_MCP_URL:      base URL override
      - GITHUB_MCP_TOOLSETS: comma-separated toolset list (overrides `toolsets`)
      - GITHUB_MCP_READONLY: "1" / "true" forces read-only mode
    """
    url = os.environ.get("GITHUB_MCP_URL", DEFAULT_REMOTE_URL)

    headers: dict[str, str] = {"Authorization": f"Bearer {pat}"}

    env_toolsets = os.environ.get("GITHUB_MCP_TOOLSETS") or toolsets
    if env_toolsets:
        headers["X-MCP-Toolsets"] = env_toolsets

    env_ro = os.environ.get("GITHUB_MCP_READONLY", "").lower() in {"1", "true", "yes"}
    if readonly or env_ro:
        headers["X-MCP-Readonly"] = "true"

    return url, headers
