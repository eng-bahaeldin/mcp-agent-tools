import json
import os
import time
from typing import Any
from dotenv import load_dotenv
from openai import AsyncOpenAI
from src.client.mcp_client import EnterpriseMCPClient

load_dotenv()

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

SYSTEM_PROMPT = """You are an Autonomous Enterprise Operations Assistant backed by Model Context Protocol (MCP) tools.
When answering operational queries:
1. Always inspect the database using `query_database` rather than guessing inventory or order values.
2. Always check live weather using `get_current_weather` when dispatch or weather risk is mentioned.
3. Always use `calculate_expression` for financial/arithmetic math instead of mental math.
4. If a tool returns a BLOCKED security status, clearly report that the operation was blocked by security policy and do NOT attempt workarounds.
5. Synthesize a concise, factual operational report once all required tool observations are gathered."""


async def run_agent_workflow(
    user_prompt: str,
    model: str = "gemini-3.5-flash",
    max_turns: int = 6,
    api_key: str | None = None,
    client_override: AsyncOpenAI | None = None,
) -> dict[str, Any]:
    """Connects to the MCP server, runs a multi-turn function-calling loop, and returns trace data."""
    resolved_key = api_key or os.getenv("GEMINI_API_KEY")
    if not client_override and not resolved_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. Add it to your .env file or Streamlit Cloud Secrets."
        )

    llm = client_override or AsyncOpenAI(
        api_key=resolved_key,
        base_url=GEMINI_OPENAI_BASE_URL,
    )
    mcp_client = EnterpriseMCPClient()
    trace: list[dict[str, Any]] = []

    try:
        discovered_tools = await mcp_client.connect()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        for turn in range(1, max_turns + 1):
            response = await llm.chat.completions.create(
                model=model,
                messages=messages,
                tools=mcp_client.openai_tools,
                tool_choice="auto",
                temperature=0.0,
            )

            assistant_msg = response.choices[0].message
            messages.append(assistant_msg.model_dump(exclude_none=True))

            if not assistant_msg.tool_calls:
                return {
                    "final_answer": assistant_msg.content or "",
                    "turns_used": turn,
                    "discovered_tools": discovered_tools,
                    "trace": trace,
                }

            for tc in assistant_msg.tool_calls:
                tool_name = tc.function.name
                raw_args = tc.function.arguments
                start_time = time.perf_counter()

                try:
                    parsed_args = json.loads(raw_args)
                    raw_output = await mcp_client.call_tool(tool_name, parsed_args)
                except json.JSONDecodeError as je:
                    parsed_args = {"_raw": raw_args}
                    raw_output = json.dumps({"status": "ARG_PARSE_ERROR", "error": str(je)})
                except Exception as exc:
                    parsed_args = {"_raw": raw_args}
                    raw_output = json.dumps({"status": "TOOL_EXEC_ERROR", "error": str(exc)})

                latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

                trace.append(
                    {
                        "turn": turn,
                        "tool_call_id": tc.id,
                        "tool_name": tool_name,
                        "arguments": parsed_args,
                        "raw_output": raw_output,
                        "latency_ms": latency_ms,
                    }
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": raw_output,
                    }
                )

        return {
            "final_answer": "Agent reached maximum reasoning turns without finalizing.",
            "turns_used": max_turns,
            "discovered_tools": discovered_tools,
            "trace": trace,
        }

    finally:
        await mcp_client.close()
