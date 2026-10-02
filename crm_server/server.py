import sqlite3
import json
import os
from fastmcp import FastMCP
DB_PATH = os.path.join(os.path.dirname(__file__), "crm.db")

mcp = FastMCP("CRM Server")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@mcp.tool()
def get_customer(customer_id: str) -> str:
    """Get customer profile by ID. Returns name, email, plan, and status."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return json.dumps({"error": f"Customer {customer_id} not found"})
    return json.dumps(dict(row))


@mcp.tool()
def get_customer_orders(customer_id: str) -> str:
    """Get all orders for a customer. Returns order history with status and amounts."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM orders WHERE customer_id = ? ORDER BY created_at DESC LIMIT 10",
        (customer_id,)
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return json.dumps({"orders": [], "message": "No orders found"})
    return json.dumps({"orders": [dict(r) for r in rows]})


@mcp.tool()
def get_policy(category: str) -> str:
    """Get support policies for a category. Categories: billing, technical, shipping, account, other."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM policies WHERE category = ?", (category.lower(),))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return json.dumps({"error": f"No policies found for category: {category}"})
    return json.dumps({"policies": [dict(r) for r in rows]})


@mcp.tool()
def get_ticket_history(customer_id: str) -> str:
    """Get previous support tickets for a customer."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM tickets WHERE customer_id = ? ORDER BY created_at DESC LIMIT 5",
        (customer_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return json.dumps({"tickets": [dict(r) for r in rows]})


@mcp.tool()
def update_ticket_status(ticket_id: str, status: str, customer_id: str) -> str:
    """Update a ticket status. Valid statuses: open, resolved, escalated, pending."""
    valid = {"open", "resolved", "escalated", "pending"}
    if status not in valid:
        return json.dumps({"error": f"Invalid status. Must be one of: {valid}"})
    conn = get_conn()
    cur = conn.cursor()
    # insert or update ticket
    cur.execute("""
        INSERT OR REPLACE INTO tickets (id, customer_id, category, status, created_at)
        VALUES (?, ?, 'support', ?, datetime('now'))
    """, (ticket_id, customer_id, status))
    conn.commit()
    conn.close()
    return json.dumps({"success": True, "ticket_id": ticket_id, "status": status})


if __name__ == "__main__":
    mcp.run(transport="stdio")