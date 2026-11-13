import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class EnterpriseMCPClient:
    def __init__(self):
        self.exit_stack = AsyncExitStack()
        self.session: ClientSession | None = None
        self.discovered_tools: list[dict[str, Any]] = []
        self.openai_tools: list[dict[str, Any]] = []

    async def connect(self) -> list[dict[str, Any]]:
        """Spawns the MCP server over stdio, performs handshake, and discovers tools."""
        env = os.environ.copy()
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{PROJECT_ROOT}{os.pathsep}{existing_pp}" if existing_pp else str(PROJECT_ROOT)
        )
        env["PYTHONUNBUFFERED"] = "1"

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.server.mcp_server"],
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        read_stream, write_stream = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self.session.initialize()

        response = await self.session.list_tools()
        self.discovered_tools = []
        self.openai_tools = []

        for tool in response.tools:
            self.discovered_tools.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema,
                }
            )
            self.openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema,
                    },
                }
            )

        return self.discovered_tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Dispatches a tool invocation over MCP stdio and extracts text output."""
        if not self.session:
            raise RuntimeError("MCP ClientSession is not connected.")

        result = await self.session.call_tool(name, arguments=arguments)
        text_parts = [block.text for block in result.content if hasattr(block, "text")]
        return "\n".join(text_parts) if text_parts else "{}"

    async def close(self):
        await self.exit_stack.aclose()
