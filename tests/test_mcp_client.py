from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.client.mcp_client import EnterpriseMCPClient
from src.client.agent_loop import run_agent_workflow


@pytest.mark.asyncio
async def test_4_dynamic_tool_discovery():
    client = EnterpriseMCPClient()
    try:
        tools = await client.connect()
        tool_names = {t["name"] for t in tools}
        assert tool_names == {"query_database", "get_current_weather", "calculate_expression"}
        for t in tools:
            assert "properties" in t["inputSchema"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_5_multi_step_chained_loop():
    def make_msg(content=None, tool_calls=None):
        msg = SimpleNamespace(content=content, tool_calls=tool_calls)

        def model_dump(exclude_none=True):
            d = {"role": "assistant"}
            if content is not None:
                d["content"] = content
            if tool_calls is not None:
                d["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ]
            return d

        msg.model_dump = model_dump
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    tc1 = SimpleNamespace(
        id="call_sql_1",
        function=SimpleNamespace(
            name="query_database",
            arguments='{"sql_query": "SELECT order_total FROM orders WHERE order_id = 4492"}',
        ),
    )
    tc2 = SimpleNamespace(
        id="call_math_2",
        function=SimpleNamespace(
            name="calculate_expression",
            arguments='{"expression": "15000 * 0.035"}',
        ),
    )

    mock_llm = AsyncMock()
    mock_llm.chat.completions.create.side_effect = [
        make_msg(tool_calls=[tc1]),
        make_msg(tool_calls=[tc2]),
        make_msg(content="Order #4492 total is $15,000.00 and shipping insurance (3.5%) is $525.00."),
    ]

    result = await run_agent_workflow(
        "Calculate 3.5% insurance on order #4492",
        max_turns=4,
        client_override=mock_llm,
    )

    assert result["turns_used"] == 3
    assert len(result["trace"]) == 2
    assert result["trace"][0]["tool_name"] == "query_database"
    assert result["trace"][1]["tool_name"] == "calculate_expression"
    assert "$525.00" in result["final_answer"]
