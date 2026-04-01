import sqlite3
from config_loader import db_config

#Load values from YAML
db_name = db_config["database"]["name"]
tables = db_config["tables"]

def create_tables():
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()


    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {tables['master']} (
            runbook_id TEXT PRIMARY KEY,
            runbook_name TEXT,
            issue_category TEXT,
            description TEXT
        )
    """)

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {tables['steps']} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            runbook_id TEXT,
            step_order INTEGER,
            step_id TEXT,
            instruction TEXT,
            step_type TEXT,
            FOREIGN KEY(runbook_id) REFERENCES {tables['master']}(runbook_id)
        )
    """)

    conn.commit()
    conn.close()

    print("DB setup completed using config.")

create_tables()
