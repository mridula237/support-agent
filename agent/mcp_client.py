import sqlite3
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "crm_server", "crm.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_customer(customer_id: str) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return json.dumps({"error": f"Customer {customer_id} not found"})
    return json.dumps(dict(row))


def get_customer_orders(customer_id: str) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM orders WHERE customer_id = ? ORDER BY created_at DESC LIMIT 10",
        (customer_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return json.dumps({"orders": [dict(r) for r in rows]})


def get_policy(category: str) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM policies WHERE category = ?", (category.lower(),))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return json.dumps({"error": f"No policies found for: {category}"})
    return json.dumps({"policies": [dict(r) for r in rows]})


def get_ticket_history(customer_id: str) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM tickets WHERE customer_id = ? ORDER BY created_at DESC LIMIT 5",
        (customer_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return json.dumps({"tickets": [dict(r) for r in rows]})


def update_ticket_status(ticket_id: str, status: str, customer_id: str) -> str:
    valid = {"open", "resolved", "escalated", "pending"}
    if status not in valid:
        return json.dumps({"error": f"Invalid status: {status}"})
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO tickets (id, customer_id, category, status, created_at)
        VALUES (?, ?, 'support', ?, datetime('now'))
    """, (ticket_id, customer_id, status))
    conn.commit()
    conn.close()
    return json.dumps({"success": True, "ticket_id": ticket_id, "status": status})


class MCPClient:
    """MCP client that calls the CRM database directly.
    
    The MCP server (crm_server/server.py) defines the canonical tool interface
    and would be used in a real deployment via stdio transport.
    This client implements the same interface for reliable local execution.
    """

    def get_tools(self) -> dict:
        return {
            "get_customer": get_customer,
            "get_customer_orders": get_customer_orders,
            "get_policy": get_policy,
            "get_ticket_history": get_ticket_history,
            "update_ticket_status": update_ticket_status,
        }

    def close(self):
        pass