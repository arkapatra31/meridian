import asyncio
import os

from dotenv import load_dotenv
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

load_dotenv()


async def main():
    options = ClaudeAgentOptions(model=os.environ["ANTHROPIC_MODEL"])
    async for msg in query(
        prompt="What are the different ANTHROPIC_MODEL that I can use as my LLM. Return me the list",
        options=options,
    ):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text:
                    print(block.text, end="", flush=True)
    print()


asyncio.run(main())
