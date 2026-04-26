import os
from threading import Lock
from dotenv import load_dotenv
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

load_dotenv()


class ClaudeClient:
    _instance: "ClaudeClient | None" = None
    _lock = Lock()

    def __init__(self, system_prompt: str | None = None):
        model = os.environ.get("ANTHROPIC_MODEL")
        if not model:
            raise RuntimeError("ANTHROPIC_MODEL is not set in the environment")
        self.model = model
        self.options = ClaudeAgentOptions(
            model=model,
            system_prompt=system_prompt,
        )
        self._client: ClaudeSDKClient | None = None

    @classmethod
    def get_instance(cls, system_prompt: str | None = None) -> "ClaudeClient":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(system_prompt)
        return cls._instance

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
