import sqlite3
from config_loader import db_config

db_name = db_config["database"]["name"]
tables = db_config["tables"]

def get_steps(runbook_id):
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()

    cur.execute(f"""
        SELECT step_id, step_order, instruction, step_type
        FROM {tables['steps']}
        WHERE runbook_id = ?
        ORDER BY step_order
    """, (runbook_id,))

    rows = cur.fetchall()
    conn.close()

    steps = {}

    for row in rows:
        step_id, step_order, instruction, step_type = row
        steps[step_id] = {
            "step_order": step_order,
            "instruction": instruction,
            "step_type": step_type
        }

    return steps

def get_all_runbooks():
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()

    cur.execute(f"""
        SELECT runbook_id, description
        FROM {tables['master']}
    """)

    rows = cur.fetchall()
    conn.close()

    return [
        {"runbook_id": r[0], "description": r[1]}
        for r in rows
    ]

def get_next_step_id(steps, current_step_id):
    ordered = sorted(steps.items(), key=lambda x: x[1]["step_order"])
    ids = [sid for sid, _ in ordered]

    idx = ids.index(current_step_id)
    if idx + 1 < len(ids):
        return ids[idx + 1]
    return "END"
