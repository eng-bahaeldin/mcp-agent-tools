try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP

from src.server.tools.sql_tool import ensure_database_seeded, execute_read_only_sql
from src.server.tools.weather_tool import fetch_city_weather
from src.server.tools.math_tool import evaluate_safe_math

mcp = FastMCP("EnterpriseOpsMCPServer")


@mcp.tool()
async def query_database(sql_query: str) -> str:
    """
    Execute a read-only SQLite SELECT query against the enterprise operations database.
    Tables:
    - customers(customer_id, name, tier, city)
    - products(sku, name, unit_price, weight_kg)
    - inventory(inventory_id, warehouse_city, sku, quantity_available)
    - orders(order_id, customer_id, sku, quantity, order_total, destination_city, status)

    Args:
        sql_query: A single valid SQLite SELECT statement. DDL/DML statements are strictly blocked.
    """
    return await execute_read_only_sql(sql_query)


@mcp.tool()
async def get_current_weather(city: str) -> str:
    """
    Retrieve real-time weather conditions, precipitation, wind speed, and logistics dispatch
    advisory for a given city using Open-Meteo.

    Args:
        city: Name of the city (e.g., "Seattle", "Portland", "Denver").
    """
    return await fetch_city_weather(city)


@mcp.tool()
async def calculate_expression(expression: str) -> str:
    """
    Deterministically evaluate an arithmetic or mathematical expression using a safe AST parser.
    Supports +, -, *, /, //, %, **, parentheses, and functions: round, abs, sqrt, ceil, floor.
    Convert percentages to decimals before calling (e.g., 3.5% -> 0.035).

    Args:
        expression: Mathematical expression string, e.g., "15000 * 0.035".
    """
    return evaluate_safe_math(expression)


if __name__ == "__main__":
    ensure_database_seeded()
    mcp.run(transport="stdio")
