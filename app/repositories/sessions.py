import json
from datetime import datetime, timezone
from typing import TypedDict

from app.core.database import database_transaction
from app.core.runbooks import Step


class SessionConflictError(Exception):
    pass


class Message(TypedDict):
    role: str
    message: str
    step_id: str | None
    created_at: str


class SessionRecord(TypedDict):
    session_id: str
    user_issue: str
    runbook_id: str
    status: str
    current_step_id: str | None
    executed_steps: list[str]
    context: dict[str, str]
    version: int
    steps: dict[str, Step]
    fact_definitions: list[dict]
    facts: dict[str, str]
    attempts: dict[str, int]
    decisions: list[dict]


def _facts_json(session: SessionRecord) -> str:
    return json.dumps({
        "definitions": session["fact_definitions"], "values": session["facts"],
        "attempts": session["attempts"], "decisions": session["decisions"],
    })


def new_message(role: str, message: str, step_id: str | None = None) -> Message:
    return {
        "role": role,
        "message": message,
        "step_id": step_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def save_turn(session: SessionRecord, messages: list[Message], *, is_new: bool) -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    next_version = session["version"] + 1
    with database_transaction() as connection:
        values = (
            session["status"], session["current_step_id"],
            json.dumps(session["executed_steps"]), json.dumps(session["context"]),
            json.dumps(session["steps"]), _facts_json(session), next_version, timestamp,
        )
        if is_new:
            connection.execute(
                """INSERT INTO agent_sessions
                (status, current_step_id, executed_steps, context_json, steps_json, facts_json,
                 version, updated_at, session_id, user_issue, runbook_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*values, session["session_id"], session["user_issue"], session["runbook_id"], timestamp),
            )
        else:
            result = connection.execute(
                """UPDATE agent_sessions SET status=?, current_step_id=?, executed_steps=?,
                context_json=?, steps_json=?, facts_json=?, version=?, updated_at=?
                WHERE session_id=? AND version=?""",
                (*values, session["session_id"], session["version"]),
            )
            if result.rowcount != 1:
                raise SessionConflictError("Session changed; reload its state before responding again.")
        connection.executemany(
            """INSERT INTO agent_messages (session_id, role, message, step_id, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            [
                (session["session_id"], item["role"], item["message"], item["step_id"], item["created_at"])
                for item in messages
            ],
        )
    return next_version


def read_session(session_id: str) -> tuple[SessionRecord, list[Message]] | None:
    with database_transaction() as connection:
        connection.execute("BEGIN")
        row = connection.execute(
            "SELECT * FROM agent_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        messages = connection.execute(
            """SELECT role, message, step_id, created_at FROM agent_messages
            WHERE session_id=? ORDER BY id""", (session_id,)
        ).fetchall()
    if row is None:
        return None
    fact_state = json.loads(row["facts_json"] or "{}")
    session = SessionRecord(
        session_id=row["session_id"],
        user_issue=row["user_issue"],
        runbook_id=row["runbook_id"],
        status=row["status"],
        current_step_id=row["current_step_id"],
        executed_steps=json.loads(row["executed_steps"]),
        context=json.loads(row["context_json"]),
        version=row["version"],
        steps=json.loads(row["steps_json"]),
        fact_definitions=fact_state.get("definitions", []),
        facts=fact_state.get("values", {}),
        attempts=fact_state.get("attempts", {}),
        decisions=fact_state.get("decisions", []),
    )
    return session, [
        Message(role=item["role"], message=item["message"], step_id=item["step_id"], created_at=item["created_at"])
        for item in messages
    ]


def get_session(session_id: str) -> SessionRecord | None:
    snapshot = read_session(session_id)
    return snapshot[0] if snapshot else None


def list_messages(session_id: str) -> list[Message]:
    with database_transaction() as connection:
        rows = connection.execute(
            """SELECT role, message, step_id, created_at FROM agent_messages
            WHERE session_id=? ORDER BY id""", (session_id,)
        ).fetchall()
    return [
        Message(role=row["role"], message=row["message"], step_id=row["step_id"], created_at=row["created_at"])
        for row in rows
    ]
