import json
import re

from app.core.config import get_db_config
from app.core.database import database_transaction
from app.core.runbooks import RunbookDefinition, Step


def get_steps(runbook_id: str) -> dict[str, Step]:
    table = get_db_config()["tables"]["steps"]
    with database_transaction() as connection:
        rows = connection.execute(
            f"""SELECT step_id, step_order, instruction, step_type, next_steps, collects, routes
            FROM {table} WHERE runbook_id=? ORDER BY step_order""", (runbook_id,)
        ).fetchall()
    if len({row["step_id"] for row in rows}) != len(rows):
        raise ValueError(f"Duplicate step IDs in {runbook_id}; re-ingest the runbook.")
    return {
        row["step_id"]: Step(
            step_order=row["step_order"], instruction=row["instruction"], step_type=row["step_type"],
            next_steps=json.loads(row["next_steps"]) if row["next_steps"] else None,
            collects=row["collects"],
            routes=json.loads(row["routes"]) if row["routes"] else None,
        )
        for row in rows
    }


def get_fact_definitions(runbook_id: str) -> list[dict]:
    table = get_db_config()["tables"]["master"]
    with database_transaction() as connection:
        row = connection.execute(
            f"SELECT facts_json FROM {table} WHERE runbook_id=?", (runbook_id,)
        ).fetchone()
    return json.loads(row["facts_json"]) if row and row["facts_json"] else []


def get_all_runbooks() -> list[dict[str, str]]:
    table = get_db_config()["tables"]["master"]
    with database_transaction() as connection:
        rows = connection.execute(
            f"SELECT runbook_id, description FROM {table} ORDER BY runbook_id"
        ).fetchall()
    return [{"runbook_id": row["runbook_id"], "description": row["description"]} for row in rows]


def insert_runbook(runbook_data: dict) -> str:
    runbook = RunbookDefinition.model_validate(runbook_data)
    tables = get_db_config()["tables"]
    runbook_id = re.sub(r"[^A-Z0-9]+", "_", runbook.runbook_name.upper()).strip("_")
    if not runbook_id:
        raise ValueError("Runbook name must contain ASCII letters or numbers")
    id_map = {step.step_id: f"{runbook_id}_{step.step_order}" for step in runbook.steps}
    with database_transaction() as connection:
        connection.execute(
            f"""INSERT INTO {tables['master']}
            (runbook_id, runbook_name, issue_category, description, facts_json)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(runbook_id) DO UPDATE SET
            runbook_name=excluded.runbook_name, issue_category=excluded.issue_category,
            description=excluded.description, facts_json=excluded.facts_json""",
            (runbook_id, runbook.runbook_name, runbook.issue_category, runbook.description,
             json.dumps([fact.model_dump() for fact in runbook.facts])),
        )
        connection.execute(f"DELETE FROM {tables['steps']} WHERE runbook_id=?", (runbook_id,))
        for step in runbook.steps:
            targets = (
                [id_map.get(target, target) for target in step.next_steps]
                if step.next_steps is not None else None
            )
            routes = (
                [{"when": route.when, "to": id_map.get(route.to, route.to)} for route in step.routes]
                if step.routes is not None else None
            )
            connection.execute(
                f"""INSERT INTO {tables['steps']}
                (step_id, runbook_id, step_order, instruction, step_type, next_steps, collects, routes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (id_map[step.step_id], runbook_id, step.step_order, step.instruction,
                 step.step_type, json.dumps(targets) if targets is not None else None,
                 step.collects, json.dumps(routes) if routes is not None else None),
            )
    return runbook_id
