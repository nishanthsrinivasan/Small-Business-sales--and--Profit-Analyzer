import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "small_business_sales.db")

def get_connection():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    except Exception as e:
        print("Database connection failed:", e)
        return None
