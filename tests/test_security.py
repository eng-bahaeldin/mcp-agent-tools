import json
import pytest
from src.server.tools.sql_tool import execute_read_only_sql
from src.server.tools.math_tool import evaluate_safe_math


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malicious_sql",
    [
        "DROP TABLE inventory;",
        "DELETE FROM orders WHERE order_id = 4492;",
        "UPDATE inventory SET quantity_available = 9999;",
        "INSERT INTO customers VALUES (999, 'Hacker', 'Admin', 'Seattle');",
        "SELECT * FROM orders; DROP TABLE inventory;--",
        "SELECT * FROM orders /* comment */ ; ATTACH DATABASE '/tmp/pwn.db' AS pwn;",
    ],
)
async def test_6_sql_ddl_dml_and_stacked_rejection(malicious_sql):
    raw = await execute_read_only_sql(malicious_sql)
    data = json.loads(raw)
    assert data["status"] == "BLOCKED"
    assert "Security Policy Violation" in data["error"]


@pytest.mark.parametrize(
    "malicious_expr",
    [
        "__import__('os').listdir('.')",
        "open('/etc/passwd').read()",
        "[x for x in (1, 2, 3)]",
        "(lambda: 1)()",
        "9 ** 999999",
    ],
)
def test_7_arbitrary_code_execution_blocked(malicious_expr):
    raw = evaluate_safe_math(malicious_expr)
    data = json.loads(raw)
    assert data["status"] == "BLOCKED"
