import sqlite3
from config_loader import db_config

db_name = db_config["database"]["name"]
tables = db_config["tables"]

def insert_runbook(data):
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()

    runbook_id = data["runbook_name"].replace(" ", "_").upper()

    #Insert master
    cur.execute(f"""
        INSERT OR REPLACE INTO {tables['master']}
        (runbook_id, runbook_name, issue_category, description)
        VALUES (?,?,?,?)
    """, (
        runbook_id,
        data["runbook_name"],
        data["issue_category"],
        data["description"]
    ))

    #Insert steps
    for step in data["steps"]:
        step_unique_id = f"{runbook_id}_{step['step_order']}"

        cur.execute(f"""
            INSERT OR REPLACE INTO {tables['steps']}
            (step_id, runbook_id, step_order, instruction, step_type)
            VALUES (?,?,?,?,?)
        """, (
            step_unique_id,
            runbook_id,
            step["step_order"],
            step["instruction"],
            step["step_type"]
        ))

    conn.commit()
    conn.close()
