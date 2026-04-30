import os
from threading import Lock
from collections.abc import AsyncIterator
from dotenv import load_dotenv
from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, Message, query

load_dotenv()


class ClaudeCodeAgent:
    _instances: "dict[str, ClaudeCodeAgent]" = {}
    _lock = Lock()

    def __init__(
        self,
        system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
        cwd: str | None = None,
        agents: dict[str, AgentDefinition] | None = None,
        model: str | None = None,
        max_turns: int | None = None,
    ):
        resolved_model = model or os.environ.get("ANTHROPIC_MODEL")
        if not resolved_model:
            raise RuntimeError("ANTHROPIC_MODEL is not set in the environment")
        self.model = resolved_model
        self.options = ClaudeAgentOptions(
            model=resolved_model,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools or ["Read", "Glob", "Grep"],
            cwd=cwd,
            permission_mode="bypassPermissions",
            agents=agents or {},
            max_turns=max_turns,
        )

    @classmethod
    def get_instance(
        cls,
        system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
        cwd: str | None = None,
        agents: dict[str, AgentDefinition] | None = None,
        model: str | None = None,
        max_turns: int | None = None,
        name: str = "default",
    ) -> "ClaudeCodeAgent":
        if name not in cls._instances:
            with cls._lock:
                if name not in cls._instances:
                    cls._instances[name] = cls(
                        system_prompt, allowed_tools, cwd, agents, model, max_turns
                    )
        return cls._instances[name]

    def run(self, prompt: str) -> AsyncIterator[Message]:
        return query(prompt=prompt, options=self.options)
