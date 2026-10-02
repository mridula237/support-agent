import sqlite3
import random
from faker import Faker
from datetime import datetime, timedelta
import os

fake = Faker()
DB_PATH = os.path.join(os.path.dirname(__file__), "crm.db")


def seed():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # customers table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            plan TEXT,
            status TEXT,
            created_at TEXT
        )
    """)

    # orders table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            customer_id TEXT,
            product TEXT,
            amount REAL,
            status TEXT,
            created_at TEXT
        )
    """)

    # tickets table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id TEXT PRIMARY KEY,
            customer_id TEXT,
            category TEXT,
            status TEXT,
            created_at TEXT
        )
    """)

    # policies table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS policies (
            id TEXT PRIMARY KEY,
            category TEXT,
            title TEXT,
            content TEXT
        )
    """)

    # seed customers
    plans = ["free", "pro", "enterprise"]
    statuses = ["active", "churned", "suspended"]
    customers = []
    for i in range(50):
        cid = f"CUST{i+1:04d}"
        customers.append((
            cid,
            fake.name(),
            fake.email(),
            random.choice(plans),
            random.choice(statuses),
            fake.date_time_this_year().isoformat()
        ))
    cur.executemany("INSERT OR IGNORE INTO customers VALUES (?,?,?,?,?,?)", customers)

    # seed orders
    products = ["Basic Plan", "Pro Plan", "Enterprise Plan", "Add-on Storage", "API Credits"]
    order_statuses = ["delivered", "pending", "refunded", "cancelled"]
    for i in range(100):
        cid = f"CUST{random.randint(1,50):04d}"
        cur.execute("INSERT OR IGNORE INTO orders VALUES (?,?,?,?,?,?)", (
            f"ORD{i+1:05d}",
            cid,
            random.choice(products),
            round(random.uniform(9.99, 299.99), 2),
            random.choice(order_statuses),
            fake.date_time_this_year().isoformat()
        ))

    # seed policies
    policy_data = [
        ("POL001", "billing", "Refund Policy",
         "Customers can request a full refund within 30 days of purchase. Pro and Enterprise customers get 60 days. Refunds are processed within 5-7 business days."),
        ("POL002", "billing", "Subscription Cancellation",
         "Subscriptions can be cancelled anytime. Access continues until the end of the billing period. No partial refunds for unused time except within the refund window."),
        ("POL003", "technical", "SLA Policy",
         "Free: best effort support. Pro: 24h response time. Enterprise: 4h response time with dedicated support channel."),
        ("POL004", "technical", "Downtime Credits",
         "If uptime falls below 99.9%, customers receive service credits. Pro: 10% credit per hour. Enterprise: 25% credit per hour."),
        ("POL005", "shipping", "Delivery Policy",
         "Standard delivery 5-7 business days. Express 2-3 days. Overnight available for Enterprise. Free shipping on orders over $50."),
        ("POL006", "account", "Account Suspension Policy",
         "Accounts are suspended for non-payment after 7 days. A 3-day grace period is given before suspension. Reactivation requires payment of outstanding balance."),
        ("POL007", "account", "Data Retention Policy",
         "On account deletion, data is retained for 30 days for recovery. After 30 days, all data is permanently deleted. Enterprise customers can request extended retention."),
        ("POL008", "other", "General Support Policy",
         "Support is available Monday-Friday 9am-6pm EST. Emergency support available 24/7 for Enterprise. Response times vary by plan tier."),
    ]
    cur.executemany("INSERT OR IGNORE INTO policies VALUES (?,?,?,?)", policy_data)

    conn.commit()
    conn.close()
    print(f"Database seeded at {DB_PATH}")
    print(f"  50 customers, 100 orders, 8 policies")


if __name__ == "__main__":
    seed()