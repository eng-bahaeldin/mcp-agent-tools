# AI Prompt Log & Security Audit

## 1. Initial Baseline Prompt
> You are a Principal AI Agent Architect specializing in tool integration and the Model Context Protocol (MCP). Build an end-to-end Python 3.11+ system featuring an MCP server with three distinct tools (`query_database`, `get_current_weather`, `calculate_expression`) using `FastMCP` over `stdio` transport and a client application executing an autonomous function-calling loop.

## 2. Security & Architectural Audit Findings

### Finding 1: Naive SQL String Filtering & Read-Write Connection
- **Vulnerability:** The initial AI draft validated SQL using `if "DROP" in query.upper()` and opened SQLite via `aiosqlite.connect("data/enterprise_ops.db")`.
- **Attack Vector:** Stacked queries with inline comments (`SELECT * FROM orders; DROP/**/TABLE inventory;--`) bypass substring checks and destroy production tables.
- **Remediation:** Added `sqlparse` comment stripping + single-statement enforcement + strict `stmt.get_type() == "SELECT"` check, paired with SQLite kernel-level `file:...?mode=ro` URI enforcement.

### Finding 2: Unrestricted `eval()` / Unbounded Exponentiation in Math Tool
- **Vulnerability:** Initial draft used `eval(expression, {"__builtins__": None}, math.__dict__)` and allowed unbounded powers (`9**9**9`), creating CPU exhaustion and Python object-graph escape risks.
- **Remediation:** Replaced `eval()` with a strict `ast.NodeVisitor` whitelist (`ast.Expression`, `ast.Constant`, `ast.BinOp`, `ast.UnaryOp`, and 5 pure math functions) plus `MAX_EXPONENT = 1000`.

### Finding 3: MCP `CallToolResult` Serialization Mismatch
- **Bug:** The initial client loop passed the raw `CallToolResult` object returned by `session.call_tool()` directly into OpenAI's `role="tool"` message content, raising `TypeError: Object of type CallToolResult is not JSON serializable`.
- **Remediation:** Extracted `.text` fields from `result.content` (`list[TextContent]`) before appending to the OpenAI message history.
