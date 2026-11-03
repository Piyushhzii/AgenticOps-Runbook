import os
import sqlite3
from contextlib import contextmanager

from app.core.config import get_db_config, resolve_path


def get_database_path():
    if os.getenv("RUNBOOK_DB_PATH"):
        return resolve_path(os.environ["RUNBOOK_DB_PATH"])
    db_config = get_db_config()
    return resolve_path(db_config["database"]["name"])


def get_connection():
    connection = sqlite3.connect(get_database_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def database_transaction():
    connection = get_connection()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database():
    with database_transaction() as connection:
        _initialize_schema(connection)


def _initialize_schema(connection: sqlite3.Connection):
    db_config = get_db_config()
    tables = db_config["tables"]

    cursor = connection.cursor()

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {tables['master']} (
            runbook_id TEXT PRIMARY KEY,
            runbook_name TEXT,
            issue_category TEXT,
            description TEXT
        )
        """
    )

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {tables['steps']} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            runbook_id TEXT,
            step_order INTEGER,
            step_id TEXT,
            instruction TEXT,
            step_type TEXT,
            FOREIGN KEY(runbook_id) REFERENCES {tables['master']}(runbook_id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_sessions (
            session_id TEXT PRIMARY KEY,
            user_issue TEXT NOT NULL,
            runbook_id TEXT NOT NULL,
            status TEXT NOT NULL,
            current_step_id TEXT,
            executed_steps TEXT NOT NULL,
            context_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            message TEXT NOT NULL,
            step_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id)
        )
        """
    )

    # Additive migrations preserve existing local runbooks and sessions.
    for table, column, definition in (
        (tables["steps"], "next_steps", "TEXT"),
        (tables["steps"], "collects", "TEXT"),
        (tables["steps"], "routes", "TEXT"),
        (tables["master"], "facts_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("agent_sessions", "version", "INTEGER NOT NULL DEFAULT 0"),
        ("agent_sessions", "steps_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("agent_sessions", "facts_json", "TEXT NOT NULL DEFAULT '{}'"),
    ):
        columns = {row["name"] for row in cursor.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_messages(session_id, id)"
    )