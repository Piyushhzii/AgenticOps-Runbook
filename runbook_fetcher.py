from db_manager import get_connection

def fetch_runbook(issue_category):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT runbook_id, runbook_name, description
        FROM runbooks
        WHERE issue_category = ?
    """, (issue_category,))

    runbook = cursor.fetchone()

    cursor.execute("""
        SELECT step_id, step_order, instruction, step_type
        FROM steps
        WHERE runbook_id = ?
        ORDER BY step_order
    """, (runbook[0],))

    steps = cursor.fetchall()

    conn.close()

    return {
        "runbook_id": runbook[0],
        "runbook_name": runbook[1],
        "description": runbook[2],
        "steps": steps
    }
