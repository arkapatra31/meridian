"""Direct MCP client for the hosted GitHub MCP server.

Drives the GitHub MCP server over JSON-RPC (Streamable HTTP transport) without
an LLM in the loop — deterministic, fast, free of token cost.

This module owns connection lifecycle and the low-level ``call_tool`` /
``list_tools`` primitives. High-level tool wrappers (``fetch_metadata``,
``list_files``, etc.) live in :mod:`.tools` and are mixed in below.
"""

import asyncio
import json
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import (
    BlobResourceContents,
    CallToolResult,
    EmbeddedResource,
    TextContent,
    TextResourceContents,
)

from .helpers import build_mcp_endpoint, parse_owner_repo
from .tools import GithubMCPTools

load_dotenv()


class GithubMCPError(RuntimeError):
    """Raised when an MCP tool call fails or returns an error result."""


class GithubMCPClient(GithubMCPTools):
    """Async, production-grade GitHub MCP client.

    One MCP session per instance — connect once, issue any number of calls,
    close on context-manager exit. Concurrent calls on a single instance are
    serialized via an internal lock (one in-flight JSON-RPC request at a time).
    """

    DEFAULT_TOOLSETS = "repos,issues,pull_requests,context"

    def __init__(
        self,
        repo_url: str,
        pat: str,
        branch: str | None = None,
        toolsets: str | None = None,
        readonly: bool = True,
    ) -> None:
        if not pat:
            raise ValueError("GitHub PAT is required (must be supplied by the caller)")

        self.repo_url = repo_url.strip()
        self.owner, self.repo = parse_owner_repo(self.repo_url)
        self.branch = branch

        self._url, self._headers = build_mcp_endpoint(
            pat=pat,
            toolsets=toolsets or self.DEFAULT_TOOLSETS,
            readonly=readonly,
        )

        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------- lifecycle

    async def connect(self) -> "GithubMCPClient":
        if self._session is not None:
            return self

        stack = AsyncExitStack()
        try:
            http_client = create_mcp_http_client(headers=self._headers)
            await stack.enter_async_context(http_client)
            read, write, _ = await stack.enter_async_context(
                streamable_http_client(url=self._url, http_client=http_client)
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        return self

    async def aclose(self) -> None:
        if self._stack is not None:
            try:
                await self._stack.aclose()
            finally:
                self._stack = None
                self._session = None

    async def __aenter__(self) -> "GithubMCPClient":
        return await self.connect()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ---------------------------------------------------------- core driver

    async def _ensure_connected(self) -> ClientSession:
        if self._session is None:
            await self.connect()
        assert self._session is not None
        return self._session

    async def list_tools(self) -> list[str]:
        """Return the names of every tool advertised by the server."""
        session = await self._ensure_connected()
        async with self._lock:
            result = await session.list_tools()
        return [t.name for t in result.tools]

    async def call_tool(self, name: str, **arguments: Any) -> Any:
        """Invoke a GitHub MCP tool by name and return the parsed payload.

        Resolution order:
          1. If any content block is an ``EmbeddedResource``, return its
             payload — text for text resources, raw bytes for blobs. Some
             GitHub MCP tools (notably ``get_file_contents``) put the actual
             data in an embedded resource and use TextContent only for status.
          2. Else, prefer ``structuredContent`` (JSON Schema-validated output).
          3. Else, concatenated text content, JSON-decoded if it looks like JSON.

        Raises :class:`GithubMCPError` if the tool reports an error.
        """
        session = await self._ensure_connected()
        async with self._lock:
            result: CallToolResult = await session.call_tool(name, arguments or None)

        if result.isError:
            raise GithubMCPError(_format_error(name, result))

        embedded = _first_embedded_resource(result.content)
        if embedded is not None:
            return embedded

        if result.structuredContent is not None:
            return _unwrap_structured(result.structuredContent)

        text = _join_text(result.content)
        return _maybe_json(text)


# ------------------------------------------------ low-level response helpers


def _unwrap_structured(structured: dict) -> Any:
    """Some servers wrap the real payload in {"result": ...}; unwrap if present."""
    if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
        return structured["result"]
    return structured


def _join_text(blocks) -> str:
    return "".join(b.text for b in blocks if isinstance(b, TextContent))


def _first_embedded_resource(blocks) -> str | bytes | None:
    """Return the payload of the first EmbeddedResource block, or None.

    Text resources -> str (decoded). Blob resources -> bytes (base64-decoded).
    """
    import base64

    for b in blocks:
        if not isinstance(b, EmbeddedResource):
            continue
        res = b.resource
        if isinstance(res, TextResourceContents):
            return res.text
        if isinstance(res, BlobResourceContents):
            return base64.b64decode(res.blob)
    return None


def _maybe_json(text: str) -> Any:
    text = text.strip()
    if not text:
        return text
    if text[0] in "{[":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return text


def _format_error(tool_name: str, result: CallToolResult) -> str:
    msg = _join_text(result.content) or "unknown error"
    return f"MCP tool `{tool_name}` failed: {msg}"
