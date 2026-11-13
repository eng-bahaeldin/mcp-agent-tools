import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import asyncio
import json
import os
import streamlit as st
from src.client.agent_loop import run_agent_workflow
from src.client.mcp_client import EnterpriseMCPClient

st.set_page_config(page_title="MCP Enterprise Ops Console", layout="wide")
st.title("Autonomous Enterprise Operations Assistant (MCP)")
st.caption("Powered by Gemini 3.5 & Zero-Trust Tool Execution over Model Context Protocol (stdio)")

DEFAULT_OPS_PROMPT = (
    "Check if our inventory in Seattle has enough stock of SKU-90210 to fulfill order #4492, "
    "verify if rainfall there will delay ground dispatch today, and calculate the total shipping "
    "insurance cost at 3.5% of the order value."
)


def resolve_gemini_api_key() -> str:
    """Loads GEMINI_API_KEY from Streamlit Cloud secrets or local .env without exposing it in UI."""
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return os.getenv("GEMINI_API_KEY", "")


with st.sidebar:
    st.header("MCP Server Inspector")
    if st.button("Refresh MCP Tool Discovery"):
        async def _discover():
            client = EnterpriseMCPClient()
            try:
                return await client.connect()
            finally:
                await client.close()

        st.session_state["discovered_tools"] = asyncio.run(_discover())

    tools = st.session_state.get("discovered_tools", [])
    if tools:
        st.success(f"Connected: {len(tools)} MCP Tools Active")
        for t in tools:
            with st.expander(f"Tool: {t['name']}"):
                st.write(t["description"])
                st.json(t["inputSchema"])
    else:
        st.info("Click 'Refresh MCP Tool Discovery' or run a query to inspect live schemas.")

    st.divider()
    st.header("Security Test Workbench")
    st.caption("Launch pre-built adversarial payloads against the MCP sandbox:")

    if st.button("Probe 1: Stacked SQL Injection (DROP TABLE)"):
        st.session_state["active_prompt"] = (
            "Query the database and execute: SELECT * FROM orders; DROP TABLE inventory;--"
        )
    if st.button("Probe 2: Math AST Code Execution (__import__)"):
        st.session_state["active_prompt"] = (
            "Evaluate the expression: __import__('os').listdir('.')"
        )
    if st.button("Load Standard Logistics Scenario"):
        st.session_state["active_prompt"] = DEFAULT_OPS_PROMPT

prompt_input = st.text_area(
    "Operator Prompt",
    value=st.session_state.get("active_prompt", DEFAULT_OPS_PROMPT),
    height=100,
)

col1, col2 = st.columns([1, 4])
with col1:
    model_choice = st.selectbox("Foundation Model", ["gemini-3.5-flash", "gemini-3.5-pro"])
with col2:
    run_clicked = st.button("Execute Autonomous Workflow", type="primary")

if run_clicked and prompt_input.strip():
    gemini_key = resolve_gemini_api_key()
    if not gemini_key:
        st.error("Server configuration error: GEMINI_API_KEY not found in .env or Streamlit Secrets.")
    else:
        with st.spinner("Spawning MCP Server over stdio and orchestrating Gemini 3.5 tool calls..."):
            result = asyncio.run(
                run_agent_workflow(prompt_input, model=model_choice, api_key=gemini_key)
            )
            st.session_state["discovered_tools"] = result["discovered_tools"]
            st.session_state["last_result"] = result

if "last_result" in st.session_state:
    res = st.session_state["last_result"]
    st.subheader("Synthesized Operational Response")
    st.markdown(res["final_answer"])

    st.divider()
    st.subheader(
        f"Live MCP Execution Timeline ({len(res['trace'])} Tool Calls across {res['turns_used']} Turns)"
    )

    for idx, step in enumerate(res["trace"], start=1):
        with st.expander(
            f"Step {idx} | Turn {step['turn']} | Tool: `{step['tool_name']}` ({step['latency_ms']} ms)",
            expanded=True,
        ):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**1. LLM Extracted Arguments**")
                st.json(step["arguments"])
            with c2:
                st.markdown("**2. Raw MCP Tool Return Payload**")
                try:
                    st.json(json.loads(step["raw_output"]))
                except json.JSONDecodeError:
                    st.code(step["raw_output"])
