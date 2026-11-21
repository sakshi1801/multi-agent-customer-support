"""Tiny SQLite layer: customers, their orders and escalation tickets (demo data)."""

import sqlite3
from contextlib import contextmanager

from app import auth, config

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    email          TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    password_hash  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id    TEXT PRIMARY KEY,
    customer_email TEXT NOT NULL,
    item        TEXT NOT NULL,
    status      TEXT NOT NULL,          -- processing | shipped | delivered | cancelled
    total       REAL NOT NULL,
    eta         TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_email TEXT,
    summary     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',   -- open | resolved
    resolution  TEXT,
    thread_id   TEXT                            -- conversation to resume when a human replies
);
"""

# Demo accounts. The shared demo password is documented in the README; it only protects fake data.
DEMO_PASSWORD = "demo1234"
SEED_CUSTOMERS = [
    ("asha@example.com", "Asha"),
    ("ravi@example.com", "Ravi"),
    ("meera@example.com", "Meera"),
]
SEED_ORDERS = [
    ("ORD-1001", "asha@example.com", "Wireless Mouse", "shipped", 24.99, "2026-11-22"),
    ("ORD-1002", "asha@example.com", "USB-C Hub", "processing", 39.50, "2026-11-25"),
    ("ORD-1003", "ravi@example.com", "Mechanical Keyboard", "delivered", 89.00, None),
    ("ORD-1004", "ravi@example.com", "Laptop Stand", "cancelled", 29.99, None),
    ("ORD-1005", "meera@example.com", "27-inch Monitor", "shipped", 219.00, "2026-11-21"),
]


@contextmanager
def connect(path: str | None = None):
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str | None = None, seed: bool = True) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        # Databases created before tickets were linked to conversations lack thread_id.
        if "thread_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(tickets)")}:
            conn.execute("ALTER TABLE tickets ADD COLUMN thread_id TEXT")
        if seed and conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO customers VALUES (?,?,?)",
                [(email, name, auth.hash_password(DEMO_PASSWORD)) for email, name in SEED_CUSTOMERS],
            )
        if seed and conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
            conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", SEED_ORDERS)
