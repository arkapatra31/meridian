"""Per-WebSocket QnA session.

One `QnaSession` wraps one `ClaudeSDKClient` and preserves multi-turn
history across user messages on the same connection. The session lifetime
equals the WS connection lifetime.

Retrieval pipeline (runs server-side before each turn):
  1. search_nodes  — keyword-score every node, take top-K seeds
  2. get_neighbours — enrich each seed with its full inbound/outbound edges
  3. get_community  — add community cluster context for the seeds' communities
  4. Format as readable text (not raw JSON) and inject as <graph_context>

This gives the model focused, pre-aggregated signal instead of a large JSON dump.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from sdk.claude_client import ClaudeClient

from .config import QnaConfig
from .prompts import SYSTEM_PROMPT
from .tools import build_context

logger = logging.getLogger("meridian.playground")


class QnaSession:
    """Multi-turn QnA over a single graph.

    `session_id` keys the `ClaudeClient` registry — must be unique per
    concurrent WS connection (a UUID is fine).

    Usage:
        async with QnaSession(session_id, graph_data, repo_url, branch) as session:
            async for chunk in session.ask("where is auth handled?"):
                ws.send_text(chunk)
    """

    def __init__(
        self,
        session_id: str,
        graph_data: dict[str, Any],
        repo_url: str,
        branch: str,
        *,
        config: QnaConfig | None = None,
    ) -> None:
        self.session_id = session_id
        self.graph_data = graph_data
        self.repo_url = repo_url
        self.branch = branch
        self.config = config or QnaConfig.default()
        self._wrapper: ClaudeClient | None = None
        self._client: ClaudeSDKClient | None = None
        self.last_result: ResultMessage | None = None

    async def __aenter__(self) -> "QnaSession":
        self._wrapper = ClaudeClient.get_instance(
            system_prompt=SYSTEM_PROMPT.format(
                repo_url=self.repo_url, branch=self.branch
            ),
            max_turns=self.config.max_turns,
            name=self.session_id,
        )
        self._client = await self._wrapper.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._wrapper is not None:
            try:
                await self._wrapper.__aexit__(exc_type, exc, tb)
            finally:
                ClaudeClient.drop_instance(self.session_id)
                self._wrapper = None
                self._client = None

    def _build_prompt(self, query: str) -> str:
        """Run the retrieval pipeline and wrap the result for the model."""
        ctx = build_context(query, self.graph_data, top_k=self.config.top_k)
        return (
            f"<graph_context>\n{ctx}\n</graph_context>\n\n"
            f"Question: {query}"
        )

    async def ask(self, query: str) -> AsyncIterator[str]:
        """Stream the assistant's text response for one user turn.

        The same underlying `ClaudeSDKClient` is reused across calls so
        prior turns remain in the model's context.
        """
        if self._client is None:
            raise RuntimeError("QnaSession not entered — use `async with`")

        self.last_result = None
        await self._client.query(self._build_prompt(query))
        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text = block.text
                        if text:
                            yield text
                    elif isinstance(block, ToolUseBlock):
                        logger.info("fired tool %s", block.name)
            elif isinstance(msg, ResultMessage):
                self.last_result = msg
