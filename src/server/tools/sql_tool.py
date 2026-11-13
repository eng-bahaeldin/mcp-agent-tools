import json
import sqlite3
from pathlib import Path
import aiosqlite
import sqlparse

DB_PATH = (Path(__file__).resolve().parents[3] / "data" / "enterprise_ops.db").resolve()

FORBIDDEN_KEYWORDS = {
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
    "ATTACH", "DETACH", "REPLACE", "CREATE", "PRAGMA", "VACUUM", "REINDEX"
}


class SecurityViolationError(Exception):
    """Raised when a SQL query violates zero-trust read-only policies."""


def ensure_database_seeded() -> None:
    """Auto-seeds data/enterprise_ops.db if missing (useful on ephemeral cloud containers)."""
    if DB_PATH.exists():
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT, tier TEXT, city TEXT);
    CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT, unit_price REAL, weight_kg REAL);
    CREATE TABLE inventory (inventory_id INTEGER PRIMARY KEY AUTOINCREMENT, warehouse_city TEXT, sku TEXT, quantity_available INTEGER);
    CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER, sku TEXT, quantity INTEGER, order_total REAL, destination_city TEXT, status TEXT);
    """)
    cur.executemany("INSERT INTO customers VALUES (?,?,?,?)", [
        (101, "Cascade Aerospace", "Enterprise", "Seattle"),
        (102, "Puget Sound Robotics", "Enterprise", "Bellevue"),
        (103, "Willamette Freight", "Standard", "Portland"),
        (104, "Bay Area BioLabs", "Enterprise", "San Francisco"),
        (105, "Sierra Cloud Systems", "Standard", "Denver"),
        (106, "Nordic Marine Supply", "Enterprise", "Tacoma"),
    ])
    cur.executemany("INSERT INTO products VALUES (?,?,?,?)", [
        ("SKU-90210", "Industrial LiDAR Sensor Array", 1250.00, 4.2),
        ("SKU-10442", "High-Torque Servo Actuator", 340.00, 1.8),
        ("SKU-55890", "Thermal Imaging Module", 890.00, 0.9),
        ("SKU-77310", "Redundant Telemetry Controller", 620.00, 1.1),
        ("SKU-88201", "Carbon Fiber Gimbal Mount", 215.00, 0.6),
    ])
    cur.executemany("INSERT INTO inventory (warehouse_city, sku, quantity_available) VALUES (?,?,?)", [
        ("Seattle", "SKU-90210", 42), ("Seattle", "SKU-10442", 115), ("Seattle", "SKU-55890", 8),
        ("Portland", "SKU-90210", 12), ("Portland", "SKU-77310", 64),
        ("San Francisco", "SKU-90210", 30), ("San Francisco", "SKU-88201", 200),
        ("Denver", "SKU-10442", 50),
    ])
    cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", [
        (4492, 101, "SKU-90210", 12, 15000.00, "Seattle", "PENDING_DISPATCH"),
        (4493, 102, "SKU-10442", 20, 6800.00, "Bellevue", "PENDING_DISPATCH"),
        (4494, 103, "SKU-55890", 10, 8900.00, "Portland", "BACKORDERED"),
        (4495, 104, "SKU-77310", 5, 3100.00, "San Francisco", "SHIPPED"),
        (4496, 105, "SKU-88201", 30, 6450.00, "Denver", "PENDING_DISPATCH"),
        (4497, 106, "SKU-90210", 4, 5000.00, "Tacoma", "PENDING_DISPATCH"),
        (4498, 101, "SKU-55890", 2, 1780.00, "Seattle", "DELIVERED"),
        (4499, 102, "SKU-77310", 15, 9300.00, "Bellevue", "PENDING_DISPATCH"),
    ])
    conn.commit()
    conn.close()


def validate_read_only_sql(sql_query: str) -> str:
    """Strips comments, blocks stacked queries, and verifies SELECT-only tokens."""
    if not sql_query or not sql_query.strip():
        raise SecurityViolationError("Empty SQL query rejected.")

    cleaned = sqlparse.format(sql_query, strip_comments=True).strip()
    statements = [s for s in sqlparse.parse(cleaned) if str(s).strip()]

    if len(statements) != 1:
        raise SecurityViolationError(
            "Security Policy Violation: Stacked or multi-statement queries are forbidden."
        )

    stmt = statements[0]
    if stmt.get_type() != "SELECT":
        raise SecurityViolationError(
            f"Security Policy Violation: Only SELECT queries are permitted (detected: {stmt.get_type()})."
        )

    for token in stmt.flatten():
        if token.is_keyword and token.normalized.upper() in FORBIDDEN_KEYWORDS:
            raise SecurityViolationError(
                f"Security Policy Violation: Forbidden keyword '{token.normalized.upper()}' detected."
            )

    return cleaned.rstrip(";")


async def execute_read_only_sql(sql_query: str) -> str:
    """Executes a validated read-only SELECT query against enterprise_ops.db."""
    ensure_database_seeded()

    try:
        safe_sql = validate_read_only_sql(sql_query)
    except SecurityViolationError as sec_err:
        return json.dumps({"status": "BLOCKED", "error": str(sec_err)})

    ro_uri = f"file:{DB_PATH.as_posix()}?mode=ro"

    try:
        async with aiosqlite.connect(ro_uri, uri=True, timeout=5.0) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(safe_sql) as cursor:
                rows = await cursor.fetchmany(100)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                results = [dict(zip(columns, row)) for row in rows]

        return json.dumps(
            {"status": "OK", "row_count": len(results), "columns": columns, "rows": results},
            indent=2,
        )
    except aiosqlite.OperationalError as op_err:
        return json.dumps({"status": "SQL_ERROR", "error": f"Query execution failed: {op_err}"})
    except Exception:
        return json.dumps({"status": "ERROR", "error": "Unexpected database execution failure."})
