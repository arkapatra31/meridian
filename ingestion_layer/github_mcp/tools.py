"""High-level GitHub MCP tool wrappers.

Each public method here maps to a single (or fixed sequence of) GitHub MCP
tool calls. They are mixed into ``GithubMCPClient`` via the ``GithubMCPTools``
mixin, which expects the host class to expose:

  - ``call_tool(name, **arguments) -> Any``
  - ``owner: str``, ``repo: str``, ``branch: str | None``

Tools advertised by the hosted GitHub MCP server (toolsets:
``repos,issues,pull_requests,context``):

    Context
      - get_me
      - get_team_members
      - get_teams

    Repos
      - get_commit
      - get_file_contents
      - get_latest_release
      - get_release_by_tag
      - get_tag
      - list_branches
      - list_commits
      - list_releases
      - list_tags
      - search_code
      - search_repositories

    Issues
      - get_label
      - issue_read
      - list_issue_types
      - list_issues
      - search_issues

    Pull Requests
      - list_pull_requests
      - pull_request_read
      - search_pull_requests

To call any tool not wrapped below, use ``client.call_tool(name, **args)``.
"""

import base64
import json
from typing import Any, Protocol


class _ToolCaller(Protocol):
    """The contract `GithubMCPTools` expects of its host class."""

    owner: str
    repo: str
    branch: str | None

    async def call_tool(self, name: str, **arguments: Any) -> Any: ...


class GithubMCPTools:
    """Mixin: high-level wrappers around individual GitHub MCP tool calls."""

    # The mixin is consumed by GithubMCPClient, which provides these attrs.
    owner: str
    repo: str
    branch: str | None

    async def call_tool(self: _ToolCaller, name: str, **arguments: Any) -> Any:  # type: ignore[empty-body]
        ...  # provided by GithubMCPClient

    # --------------------------------------------------------------- methods

    async def fetch_metadata(self) -> dict:
        """Repository metadata (description, default branch, language, etc.)."""
        result = await self.call_tool(
            "search_repositories",
            query=f"repo:{self.owner}/{self.repo}",
            page=1,
            perPage=1,
        )
        items = _items(result)
        if not items:
            from .client import GithubMCPError

            raise GithubMCPError(f"Repository not found: {self.owner}/{self.repo}")
        return items[0]

    async def list_files(self, path: str = "") -> list[str]:
        """Non-recursive directory listing. Pass a path to drill in."""
        result = await self.call_tool(
            "get_file_contents",
            owner=self.owner,
            repo=self.repo,
            path=path,
            **({"branch": self.branch} if self.branch else {}),
        )
        entries = result if isinstance(result, list) else _items(result)
        return [e["path"] for e in entries if isinstance(e, dict) and "path" in e]

    async def get_file(self, path: str) -> str:
        """Fetch a single file's contents.

        ``call_tool`` already unwraps EmbeddedResource payloads, so for text
        files this returns a ``str`` directly. Binary files come back as
        ``bytes`` and are base64-encoded for transport.
        """
        result = await self.call_tool(
            "get_file_contents",
            owner=self.owner,
            repo=self.repo,
            path=path,
            **({"branch": self.branch} if self.branch else {}),
        )
        if isinstance(result, str):
            return result
        if isinstance(result, bytes):
            return base64.b64encode(result).decode("ascii")
        if isinstance(result, dict):
            if "content" in result:
                return _decode_content(result)
            if "text" in result:
                return str(result["text"])
        return json.dumps(result)

    async def get_head_sha(self) -> str:
        """Latest commit SHA on the configured branch (or default branch)."""
        commits = await self.list_commits(limit=1)
        if not commits:
            from .client import GithubMCPError

            raise GithubMCPError(f"No commits on {self.owner}/{self.repo}")
        first = commits[0]
        return str(first.get("sha") or first.get("oid") or "")

    async def list_commits(self, limit: int = 20) -> list[dict]:
        result = await self.call_tool(
            "list_commits",
            owner=self.owner,
            repo=self.repo,
            perPage=limit,
            **({"sha": self.branch} if self.branch else {}),
        )
        return list(result) if isinstance(result, list) else _items(result)

    async def commits_between(
        self,
        base_sha: str,
        head_sha: str,
        *,
        max_pages: int = 5,
        per_page: int = 100,
    ) -> list[dict]:
        """Commits reachable from `head_sha` but not `base_sha` (newest first).

        The hosted GitHub MCP server doesn't expose `compare_commits`, so we
        page `list_commits` from HEAD and stop as soon as we hit `base_sha`.
        Bounded by `max_pages * per_page` to avoid runaway paging on a stale
        anchor — caller should treat a hit on the cap as "previous SHA too
        far back; treat as full re-sync".
        """
        if base_sha == head_sha:
            return []

        collected: list[dict] = []
        for page in range(1, max_pages + 1):
            batch = await self.call_tool(
                "list_commits",
                owner=self.owner,
                repo=self.repo,
                sha=head_sha,
                page=page,
                perPage=per_page,
            )
            items = list(batch) if isinstance(batch, list) else _items(batch)
            if not items:
                break
            for entry in items:
                sha = str(entry.get("sha") or entry.get("oid") or "")
                if sha == base_sha:
                    return collected
                collected.append(entry)
            if len(items) < per_page:
                break
        return collected

    async def list_pull_requests(self, state: str = "open") -> list[dict]:
        result = await self.call_tool(
            "list_pull_requests",
            owner=self.owner,
            repo=self.repo,
            state=state,
        )
        return list(result) if isinstance(result, list) else _items(result)

    async def list_issues(self, state: str = "open") -> list[dict]:
        result = await self.call_tool(
            "list_issues",
            owner=self.owner,
            repo=self.repo,
            state=state,
        )
        return list(result) if isinstance(result, list) else _items(result)


# ----------------------------------------------------------- response helpers


def _items(payload: Any) -> list:
    """GitHub MCP often wraps results as {items: [...]} or {data: [...]}."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "data", "results", "value"):
            v = payload.get(key)
            if isinstance(v, list):
                return v
    return []


def _decode_content(file_payload: dict) -> str:
    """Decode the `content` field from a GitHub `get_file_contents` payload."""
    encoding = file_payload.get("encoding")
    content = file_payload.get("content", "")
    if encoding == "base64":
        return base64.b64decode(content).decode("utf-8", errors="replace")
    return str(content)
