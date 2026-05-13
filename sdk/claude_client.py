"""Wrapper around `ClaudeSDKClient` (stateful, multi-turn).

Keyed registry — one instance per logical `name`. Mirrors the pattern used
by `ClaudeCodeAgent`. Callers requesting the same `name` get the same
underlying client (and therefore the same in-context history); different
names are isolated.

Use `name=<unique-session-id>` for things that must not share state across
callers (e.g. per-WebSocket QnA sessions). Use `name="default"` for the
process-wide single-shot client.
"""

from __future__ import annotations

import os
from threading import Lock

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from dotenv import load_dotenv

load_dotenv()


class ClaudeClient:
    _instances: "dict[str, ClaudeClient]" = {}
    _lock = Lock()

    def __init__(
        self,
        system_prompt: str | None = None,
        *,
        allowed_tools: list[str] | None = None,
        cwd: str | None = None,
        permission_mode: str | None = None,
        max_turns: int | None = None,
        model: str | None = None,
    ):
        resolved_model = model or os.environ.get("ANTHROPIC_MODEL")
        if not resolved_model:
            raise RuntimeError("ANTHROPIC_MODEL is not set in the environment")
        self.model = resolved_model

        opts: dict = {
            "model": resolved_model,
            "system_prompt": system_prompt,
        }
        if allowed_tools is not None:
            opts["allowed_tools"] = allowed_tools
        if cwd is not None:
            opts["cwd"] = cwd
        if permission_mode is not None:
            opts["permission_mode"] = permission_mode
        if max_turns is not None:
            opts["max_turns"] = max_turns

        self.options = ClaudeAgentOptions(**opts)
        self._client: ClaudeSDKClient | None = None

    @classmethod
    def get_instance(
        cls,
        system_prompt: str | None = None,
        *,
        allowed_tools: list[str] | None = None,
        cwd: str | None = None,
        permission_mode: str | None = None,
        max_turns: int | None = None,
        model: str | None = None,
        name: str = "default",
    ) -> "ClaudeClient":
        """Return the registry entry for `name`, creating it on first call.

        Construction args are honoured only on the first call for a given
        `name`; subsequent calls ignore them and return the cached instance.
        """
        if name not in cls._instances:
            with cls._lock:
                if name not in cls._instances:
                    cls._instances[name] = cls(
                        system_prompt,
                        allowed_tools=allowed_tools,
                        cwd=cwd,
                        permission_mode=permission_mode,
                        max_turns=max_turns,
                        model=model,
                    )
        return cls._instances[name]

    @classmethod
    def drop_instance(cls, name: str) -> None:
        """Remove a keyed instance from the registry. Caller is responsible
        for having already exited any active `async with` on that instance."""
        with cls._lock:
            cls._instances.pop(name, None)

    @property
    def client(self) -> ClaudeSDKClient:
        if self._client is None:
            self._client = ClaudeSDKClient(options=self.options)
        return self._client

    async def __aenter__(self) -> ClaudeSDKClient:
        await self.client.__aenter__()
        return self.client

    async def __aexit__(self, exc_type, exc, tb):
        if self._client is not None:
            await self._client.__aexit__(exc_type, exc, tb)
            self._client = None
