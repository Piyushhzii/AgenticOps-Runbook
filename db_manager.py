import sqlite3
from config_loader import runbook_config

DB_PATH = runbook_config["database"]["db_path"]

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
