"""Tiny SQLite layer: customers' orders and escalation tickets (demo data)."""

import sqlite3
from contextlib import contextmanager

from app import config

SCHEMA = """
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
    resolution  TEXT
);
"""

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
        if seed and conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
            conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", SEED_ORDERS)
