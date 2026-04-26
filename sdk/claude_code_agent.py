import os
from threading import Lock
from collections.abc import AsyncIterator
from dotenv import load_dotenv
from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, Message, query

load_dotenv()


class ClaudeCodeAgent:
    _instance: "ClaudeCodeAgent | None" = None
    _lock = Lock()

    def __init__(
        self,
        system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
        cwd: str | None = None,
        agents: dict[str, AgentDefinition] | None = None,
    ):
        model = os.environ.get("ANTHROPIC_MODEL")
        if not model:
            raise RuntimeError("ANTHROPIC_MODEL is not set in the environment")
        self.model = model
        self.options = ClaudeAgentOptions(
            model=model,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools or ["Read", "Glob", "Grep"],
            cwd=cwd,
            permission_mode="bypassPermissions",
            agents=agents or {},
        )

    @classmethod
    def get_instance(
        cls,
        system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
        cwd: str | None = None,
        agents: dict[str, AgentDefinition] | None = None,
    ) -> "ClaudeCodeAgent":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(system_prompt, allowed_tools, cwd, agents)
        return cls._instance

    def run(self, prompt: str) -> AsyncIterator[Message]:
        return query(prompt=prompt, options=self.options)
