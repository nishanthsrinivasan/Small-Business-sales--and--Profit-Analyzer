import sqlite3
import os
import shutil

DB_NAME = "small_business_sales.db"

def get_db_path():
    """
    Returns correct DB path for:
    - Local
    - Render
    - Hugging Face
    """
    # Hugging Face persistent storage
    if os.path.exists("/data"):
        return os.path.join("/data", DB_NAME)
    # Local / Render
    return os.path.join(os.getcwd(), DB_NAME)
def ensure_db_exists():
    """
    Fixes 'no such table' issue by ensuring correct DB file is used
    """
    db_path = get_db_path()
    # If DB already exists → OK
    if os.path.exists(db_path):
        return
    # If running in Hugging Face → copy DB to /data
    if db_path.startswith("/data"):
        if os.path.exists(DB_NAME):
            shutil.copy(DB_NAME, db_path)
        else:
            raise Exception("❌ small_business_sales.db NOT FOUND in project!")
    else:
        raise Exception("❌ Database file missing!")
def get_connection():
    """
    Main DB connection
    """
    ensure_db_exists()
    conn = sqlite3.connect(
        get_db_path(),
        check_same_thread=False,
        timeout=20
    )
    conn.row_factory = sqlite3.Row
    # Prevent locking issue
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn