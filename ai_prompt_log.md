# AI Prompt Log & Security Engineering Audit

## 1. Initial Baseline Prompt Used to Generate Prototype

> **Prompt:**
> You are a Principal AI Agent Architect specializing in tool integration and the Model Context Protocol (MCP). Build an end-to-end Python 3.11+ system featuring an MCP server with three distinct tools and a client application executing an autonomous function-calling loop.
>
> **Architecture Requirements:**
> 1. MCP Server (`src/server/mcp_server.py`) using the official MCP Python SDK (`FastMCP`) over `stdio` transport:
>    - Tool 1: `query_database(sql_query: str) -> str` (Read-only SQLite access to `data/enterprise_ops.db`)
>    - Tool 2: `get_current_weather(city: str) -> str` (Async Open-Meteo geocoding + forecast client via `httpx.AsyncClient`)
>    - Tool 3: `calculate_expression(expression: str) -> str` (Deterministic AST-based math evaluator without `eval()` or `exec()`)
> 2. MCP Client & Agent Loop (`src/client/mcp_client.py` & `src/client/agent_loop.py`):
>    - Connects via `stdio`, dynamically discovers tools via `session.list_tools()`, converts `inputSchema` to OpenAI-compatible function definitions, and orchestrates a multi-turn function-calling loop (`max_turns=6`) with proper `tool_call_id` and `role="tool"` reconciliation.

---

## 2. Security & Protocol Audit Findings (Before & After Refactorings)

### Finding 1: Naive SQL Keyword Filtering & Read-Write Database Connection
- **Severity:** Critical (SQL Injection / Data Destruction)
- **Vulnerability in AI Draft:** The initial AI-generated `sql_tool.py` checked `if any(word in sql_query.upper() for word in ["DROP", "DELETE", "UPDATE"])` and opened `data/enterprise_ops.db` using a standard read-write SQLite connection (`aiosqlite.connect("data/enterprise_ops.db")`).
- **Exploit Vector:** An attacker or prompt-injected payload could bypass substring checks using inline SQL comments (`SELECT * FROM orders; DROP/**/TABLE inventory;--`) or attach external database files (`ATTACH DATABASE`), resulting in permanent table deletion.
- **Remediation:** Enforced defense-in-depth using `sqlparse` comment stripping, single-statement verification (blocking stacked `;` queries), strict `SELECT` statement type enforcement, a flattened keyword token scan, and kernel-level SQLite read-only URI mode (`?mode=ro`).

```python
# BEFORE (Vulnerable AI Prototype)
async def execute_sql(sql_query: str) -> str:
    forbidden = ["DROP", "DELETE", "UPDATE", "INSERT"]
    if any(word in sql_query.upper() for word in forbidden):
        return "Error: Forbidden SQL keyword"
    async with aiosqlite.connect("data/enterprise_ops.db") as db:
        cursor = await db.execute(sql_query)
        rows = await cursor.fetchall()
        return str(rows)

# AFTER (Zero-Trust Hardened Implementation in src/server/tools/sql_tool.py)
def validate_read_only_sql(sql_query: str) -> str:
    cleaned = sqlparse.format(sql_query, strip_comments=True).strip()
    statements = [s for s in sqlparse.parse(cleaned) if str(s).strip()]
    if len(statements) != 1:
        raise SecurityViolationError("Stacked or multi-statement queries are forbidden.")
    stmt = statements[0]
    if stmt.get_type() != "SELECT":
        raise SecurityViolationError(f"Only SELECT queries are permitted (detected: {stmt.get_type()}).")
    for token in stmt.flatten():
        if token.is_keyword and token.normalized.upper() in FORBIDDEN_KEYWORDS:
            raise SecurityViolationError(f"Forbidden keyword '{token.normalized.upper()}' detected.")
    return cleaned.rstrip(";")

ro_uri = f"file:{DB_PATH.as_posix()}?mode=ro"
async with aiosqlite.connect(ro_uri, uri=True, timeout=5.0) as db:
    ...
```

---

### Finding 2: Unrestricted `eval()` Sandbox Escape & Unbounded Exponentiation DoS
- **Severity:** Critical (Arbitrary Code Execution & CPU Exhaustion)
- **Vulnerability in AI Draft:** The initial draft implemented math evaluation via `eval(expression, {"__builtins__": None}, math.__dict__)` and placed no cap on exponentiation (`**`).
- **Exploit Vector:**
  1. Clearing `__builtins__` in Python does **not** prevent sandbox escapes—payloads like `[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings']` traverse Python's object hierarchy to achieve Remote Code Execution (RCE).
  2. Expressions such as `9 ** 999999` trigger massive arbitrary-precision integer allocation, freezing the MCP server process.
- **Remediation:** Eliminated `eval()` entirely in favor of `ast.parse(..., mode="eval")` walked by a custom `SafeMathEvaluator(ast.NodeVisitor)` that strictly whitelists numeric `Constant`, `BinOp`, `UnaryOp`, and 5 pure `math` functions, while capping exponents at `MAX_EXPONENT = 1000`.

```python
# BEFORE (Vulnerable AI Prototype)
def calculate(expression: str) -> str:
    allowed = {k: v for k, v in math.__dict__.items() if not k.startswith("__")}
    return str(eval(expression, {"__builtins__": None}, allowed))

# AFTER (AST Whitelist Sandbox in src/server/tools/math_tool.py)
class SafeMathEvaluator(ast.NodeVisitor):
    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise UnsafeExpressionError(f"Unsupported constant type: {type(node.value).__name__}")

    def visit_BinOp(self, node: ast.BinOp):
        op_func = BINARY_OPS.get(type(node.op))
        if not op_func:
            raise UnsafeExpressionError(f"Unsupported binary operator: {type(node.op).__name__}")
        left, right = self.visit(node.left), self.visit(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise UnsafeExpressionError(f"Exponent {right} exceeds safety limit ({MAX_EXPONENT}).")
        return op_func(left, right)

    def generic_visit(self, node: ast.AST):
        raise UnsafeExpressionError(f"Disallowed syntax construct '{type(node).__name__}'.")
```

---

### Finding 3: MCP `CallToolResult` Serialization & Subprocess `PYTHONPATH` Failures
- **Severity:** High (Protocol Crash / Broken Multi-Turn Loop)
- **Bug in AI Draft:**
  1. `EnterpriseMCPClient.call_tool()` returned the raw `CallToolResult` Pydantic object from `session.call_tool()` instead of extracting `.text` from `result.content`, causing `TypeError: Object of type CallToolResult is not JSON serializable` when building the next LLM turn payload.
  2. When launched from Streamlit (`streamlit run src/app.py`), `StdioServerParameters` did not pass `PYTHONPATH` pointing to the repository root, causing the child `python -m src.server.mcp_server` process to exit immediately with `ModuleNotFoundError: No module named 'src'`.
- **Remediation:** Extracted `block.text` from `TextContent` items in `result.content` and explicitly injected `PYTHONPATH=str(PROJECT_ROOT)` into `StdioServerParameters(env=env)`.

```python
# BEFORE (Broken MCP Client Dispatch)
async def call_tool(self, name: str, arguments: dict) -> str:
    return await self.session.call_tool(name, arguments)

# AFTER (Protocol-Compliant TextContent Extraction in src/client/mcp_client.py)
async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
    if not self.session:
        raise RuntimeError("MCP ClientSession is not connected.")
    result = await self.session.call_tool(name, arguments=arguments)
    text_parts = [block.text for block in result.content if hasattr(block, "text")]
    return "\n".join(text_parts) if text_parts else "{}"
```

---

## 3. Verification Summary
- **Automated Security & Functional QA (`uv run pytest -v`):** All 14 test cases pass across `test_server_tools.py`, `test_mcp_client.py`, and `test_security.py`, verifying read-only SQLite isolation, AST math sandboxing, dynamic MCP tool discovery, and multi-turn loop termination.