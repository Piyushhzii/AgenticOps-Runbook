import copy
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app.core.database import database_transaction, initialize_database
from app.core.config import BASE_DIR
from app.repositories.runbooks import get_steps, insert_runbook
from app.repositories.sessions import SessionConflictError, get_session, new_message, save_turn
from app.services.support_agent import (
    ASK_AGAIN, InvalidDecisionError, RunbookResolutionError, SessionInactiveError,
    SessionNotFoundError, SupportAgentService,
)


RUNBOOK = {
    "runbook_name": "Test Login",
    "issue_category": "Authentication",
    "description": "Triage login problems without pretending to execute external actions.",
    "steps": [
        {"step_id": "ask", "step_order": 1, "instruction": "What error do you see?", "step_type": "input"},
        {
            "step_id": "check", "step_order": 2, "instruction": "Check the account in the admin system.",
            "step_type": "message", "next_steps": ["verify", "ESCALATE"],
        },
        {
            "step_id": "verify", "step_order": 3, "instruction": "Can you log in now?",
            "step_type": "input", "next_steps": ["END", "ESCALATE"],
        },
    ],
}


def stub_reply(**kwargs):
    return f"Please help with: {kwargs['current_step']['instruction']}"


KEYWORD_FACTS = (
    ("password is wrong", {"error_type": "wrong_password"}),
    ("account locked", {"error_type": "account_locked"}),
    ("is locked", {"account_locked": "yes"}),
    ("reset complete", {"reset_done": "yes"}),
    ("works now", {"login_works": "yes"}),
    ("healthy", {"monitoring_status": "healthy"}),
    ("cleared", {"recovered": "yes"}),
)


def keyword_facts(**kwargs):
    message = kwargs["message"].lower()
    facts = {}
    for phrase, values in KEYWORD_FACTS:
        if phrase in message:
            facts.update(values)
    return facts


LOGIN_RUNBOOK = Path(BASE_DIR) / "data" / "reviewed" / "login_issue.json"


def evidence_following_reasoner(**kwargs):
    """Stands in for an LLM that follows the documented conditions."""
    allowed = kwargs["allowed_next_steps"]
    if kwargs["suggested_next_step"]:
        return {"next_step": kwargs["suggested_next_step"], "reason": "Evidence matches the rule."}
    if ASK_AGAIN in allowed:
        return {"next_step": ASK_AGAIN, "reason": "Reply is unclear."}
    return {"next_step": allowed[-1], "reason": "Otherwise branch."}


class IsolatedDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {
            "RUNBOOK_DB_PATH": os.path.join(self.directory.name, "test.db"),
            "OPS_ENV": "development",
            "OPS_API_KEY": "",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        initialize_database()
        self.runbook_id = insert_runbook(copy.deepcopy(RUNBOOK))
        self.service = self.make_service()

    def make_service(self, **overrides):
        dependencies = {
            "runbook_selector": lambda issue: self.runbook_id,
            "step_reasoner": lambda **kwargs: kwargs["allowed_next_steps"][0],
            "response_generator": stub_reply,
            "fact_extractor": keyword_facts,
        }
        dependencies.update(overrides)
        return SupportAgentService(**dependencies)

    def start_at_check(self):
        state = self.service.start_session("I cannot log in")
        return self.service.submit_user_response(
            state["session_id"], "Account error", expected_version=state["version"],
        )


class SupportAgentServiceTest(IsolatedDatabaseTest):
    def test_manual_checkpoints_never_use_model_generated_action_claims(self):
        for instruction, false_claim in (
            ("Check the payment status using the payment gateway API or admin dashboard.",
             "I'm checking the status of that payment now."),
            ("Check in the admin system whether the user account is locked.",
             "I'll have our team check the account status right away."),
        ):
            with self.subTest(instruction=instruction):
                runbook = copy.deepcopy(RUNBOOK)
                runbook["steps"][1]["instruction"] = instruction
                insert_runbook(runbook)
                state = self.service.start_session("Test operational issue")
                generator = Mock(return_value=false_claim)
                service = self.make_service(response_generator=generator)
                state = service.submit_user_response(state["session_id"], "TEST-REFERENCE", 1)
                generator.assert_not_called()
                reply = state["messages"][-1]["message"]
                self.assertIn(instruction, reply)
                self.assertIn("authorized operator", reply)
                self.assertIn("/escalate", reply)
                self.assertNotIn(false_claim, reply)
                self.assertTrue(state["awaiting_confirmation"])
                self.assertEqual(self.service.get_session_state(state["session_id"])["messages"][-1]["message"], reply)

    def test_graph_waits_for_manual_confirmation_and_completes(self):
        state = self.service.start_session("I cannot log in")
        self.assertEqual(state["trace"], ["select_runbook", "inspect_step", "respond"])
        self.assertEqual(state["version"], 1)
        self.assertTrue(state["awaiting_user_input"])
        self.assertFalse(state["awaiting_confirmation"])
        self.assertEqual(state["executed_steps"], [])

        state = self.service.submit_user_response(state["session_id"], "Account error", 1)
        self.assertTrue(state["awaiting_confirmation"])
        self.assertEqual(state["current_step"]["step_id"], "TEST_LOGIN_2")
        self.assertEqual(state["context"], {"TEST_LOGIN_1": "Account error"})
        self.assertNotIn("account_status", state["context"])
        self.assertIn("no system action has been executed", state["messages"][-1]["message"])
        self.assertEqual(state["trace"], [
            "inspect_step", "collect_evidence", "route_step", "inspect_step", "respond",
        ])

        state = self.service.submit_user_response(state["session_id"], "Operator checked: not locked", 2)
        self.assertFalse(state["awaiting_confirmation"])
        state = self.service.submit_user_response(state["session_id"], "Login works", 3)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["version"], 4)
        self.assertIsNone(state["current_step"])
        self.assertFalse(state["awaiting_user_input"])
        self.assertEqual(len(state["executed_steps"]), 3)
        self.assertIn("does not independently verify resolution", state["messages"][-1]["message"])
        with self.assertRaises(SessionInactiveError):
            self.service.submit_user_response(state["session_id"], "again", 4)

    def test_invalid_selection_does_not_create_session(self):
        with self.assertRaises(RunbookResolutionError):
            self.make_service(runbook_selector=lambda issue: "INVENTED").start_session("Unknown issue")
        with database_transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM agent_sessions").fetchone()[0], 0)

    def test_unknown_session_and_invalid_input(self):
        with self.assertRaises(SessionNotFoundError):
            self.service.get_session_state("unknown")
        for text in ("  ", "x" * 8001):
            with self.assertRaises(ValueError):
                self.service.start_session(text)

    def test_unknown_route_rolls_back_whole_turn(self):
        state = self.start_at_check()
        service = self.make_service(step_reasoner=lambda **kwargs: "TEST_LOGIN_1")
        with self.assertRaises(InvalidDecisionError):
            service.submit_user_response(state["session_id"], "Operator checked account", 2)
        self.assertEqual(self.service.get_session_state(state["session_id"])["messages"], state["messages"])
        self.assertEqual(get_session(state["session_id"])["version"], 2)

    def test_premature_end_is_rejected(self):
        state = self.start_at_check()
        service = self.make_service(step_reasoner=lambda **kwargs: "END")
        with self.assertRaises(InvalidDecisionError):
            service.submit_user_response(state["session_id"], "Check is inconclusive", 2)

    def test_response_failure_does_not_save_partial_turn(self):
        state = self.start_at_check()

        def fail(**kwargs):
            raise RuntimeError("Simulated response outage")

        with self.assertRaises(RuntimeError):
            self.make_service(response_generator=fail).submit_user_response(
                state["session_id"], "Error evidence", 2,
            )
        self.assertEqual(self.service.get_session_state(state["session_id"])["context"], state["context"])
        self.assertEqual(self.service.get_session_state(state["session_id"])["messages"], state["messages"])

    def test_escalation_is_explicit_and_does_not_claim_ticket_creation(self):
        state = self.service.start_session("Login error")
        state = self.service.submit_user_response(state["session_id"], "/escalate", 1)
        self.assertEqual(state["status"], "escalated")
        self.assertEqual(state["executed_steps"], [])
        self.assertIn("No external ticket", state["messages"][-1]["message"])

    def test_branch_can_escalate(self):
        state = self.start_at_check()
        state = self.make_service(step_reasoner=lambda **kwargs: "ESCALATE").submit_user_response(
            state["session_id"], "Could not verify account", 2,
        )
        self.assertEqual(state["status"], "escalated")

    def test_restart_resumes_persisted_session(self):
        state = self.start_at_check()
        resumed = self.make_service().get_session_state(state["session_id"])
        self.assertEqual(resumed["current_step"], state["current_step"])
        self.assertEqual(resumed["version"], state["version"])
        self.assertEqual(resumed["messages"], state["messages"])

    def test_runbook_snapshot_survives_reingestion(self):
        state = self.service.start_session("Login error")
        changed = copy.deepcopy(RUNBOOK)
        changed["steps"][0]["instruction"] = "New instruction"
        insert_runbook(changed)
        self.assertEqual(
            self.service.get_session_state(state["session_id"])["current_step"]["instruction"],
            "What error do you see?",
        )
        self.assertEqual(self.service.start_session("Login error")["current_step"]["instruction"], "New instruction")

    def test_stale_version_is_rejected(self):
        state = self.start_at_check()
        with self.assertRaises(SessionConflictError):
            self.service.submit_user_response(state["session_id"], "Duplicate response", 1)
        self.assertEqual(get_session(state["session_id"])["version"], 2)

    def test_concurrent_turns_only_commit_once(self):
        state = self.start_at_check()
        barrier = threading.Barrier(2)

        def synchronized_reply(**kwargs):
            barrier.wait(timeout=10)
            return stub_reply(**kwargs)

        service = self.make_service(response_generator=synchronized_reply)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(service.submit_user_response, state["session_id"], "Evidence", 2)
                for _ in range(2)
            ]
            outcomes = []
            for future in futures:
                try:
                    outcomes.append(future.result(timeout=15))
                except SessionConflictError as exc:
                    outcomes.append(exc)
        self.assertEqual(sum(isinstance(item, SessionConflictError) for item in outcomes), 1)
        saved = self.service.get_session_state(state["session_id"])
        self.assertEqual(saved["version"], 3)
        self.assertEqual(len(saved["messages"]), 6)

    def test_messages_and_state_rollback_together_on_database_error(self):
        state = self.service.start_session("Login error")
        record = get_session(state["session_id"])
        self.assertIsNotNone(record)
        if record is None:
            self.fail("Session must exist")
        record["context"]["test"] = "must not save"
        with database_transaction() as connection:
            connection.execute(
                """CREATE TRIGGER reject_message BEFORE INSERT ON agent_messages
                BEGIN SELECT RAISE(ABORT, 'Simulated message write failure'); END"""
            )
        with self.assertRaises(sqlite3.IntegrityError):
            save_turn(record, [new_message("user", "New evidence")], is_new=False)
        self.assertEqual(get_session(state["session_id"])["version"], 1)
        self.assertEqual(get_session(state["session_id"])["context"], {})


class RunbookRepositoryTest(IsolatedDatabaseTest):
    def test_reingestion_replaces_steps_without_duplicates(self):
        insert_runbook(copy.deepcopy(RUNBOOK))
        self.assertEqual(len(get_steps(self.runbook_id)), 3)
        with database_transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM runbook_steps").fetchone()[0], 3)

    def test_invalid_runbooks_rejected_without_changing_existing_data(self):
        for target in ("missing", "ask"):
            invalid = copy.deepcopy(RUNBOOK)
            invalid["steps"][1]["next_steps"] = [target]
            with self.assertRaises(ValidationError):
                insert_runbook(invalid)
        invalid = copy.deepcopy(RUNBOOK)
        invalid["steps"][0]["step_type"] = "shell"
        with self.assertRaises(ValidationError):
            insert_runbook(invalid)
        self.assertEqual(len(get_steps(self.runbook_id)), 3)

    def test_migrations_are_repeatable(self):
        initialize_database()
        initialize_database()
        self.assertEqual(len(get_steps(self.runbook_id)), 3)

    def test_example_use_case_ingests_and_routes_without_provider_calls(self):
        from scripts.ingest_runbooks import ingest

        source = Path(BASE_DIR) / "data" / "service_degradation.json"
        ingest([str(source)])
        self.runbook_id = "SERVICE_DEGRADATION_TRIAGE"
        service = self.make_service()
        state = service.start_session("Checkout has elevated latency")
        state = service.submit_user_response(state["session_id"], "Checkout production since 10:00", 1)
        self.assertTrue(state["awaiting_confirmation"])
        state = service.submit_user_response(state["session_id"], "Operator reports healthy monitoring", 2)
        state = service.submit_user_response(state["session_id"], "Alerts cleared after observation", 3)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["facts"]["monitoring_status"], "healthy")

    def test_invalid_conditional_routes_are_rejected(self):
        base = json.loads(LOGIN_RUNBOOK.read_text(encoding="utf-8"))
        mutations = (
            lambda rb: rb["steps"][0]["routes"].pop(),  # no otherwise route
            lambda rb: rb["steps"][0]["routes"][0].update(when={"unknown_fact": "x"}),
            lambda rb: rb["steps"][0]["routes"][0].update(when={"error_type": "invented"}),
            lambda rb: rb["steps"][3].update(collects="undeclared"),
            lambda rb: rb["steps"][3]["routes"][0].update(to="ask_error"),  # backward
        )
        for mutate in mutations:
            runbook = copy.deepcopy(base)
            mutate(runbook)
            with self.assertRaises(ValidationError):
                insert_runbook(runbook)


class ConditionalRunbookTest(IsolatedDatabaseTest):
    def setUp(self):
        super().setUp()
        self.runbook_id = insert_runbook(json.loads(LOGIN_RUNBOOK.read_text(encoding="utf-8")))
        self.last_expected = ""
        self.decision_calls = []

        def capture_reply(**kwargs):
            self.last_expected = kwargs["expected_answer"]
            return stub_reply(**kwargs)

        def recording_reasoner(**kwargs):
            self.decision_calls.append(kwargs)
            return evidence_following_reasoner(**kwargs)

        self.service = self.make_service(
            response_generator=capture_reply, step_reasoner=recording_reasoner,
        )

    def reply(self, state, message):
        return self.service.submit_user_response(state["session_id"], message, state["version"])

    def step(self, state):
        return state["current_step"]["step_id"].removeprefix(f"{self.runbook_id}_")

    def test_wrong_password_goes_straight_to_reset(self):
        state = self.service.start_session("I need help with login issue troubleshooting")
        self.assertEqual(self.step(state), "1")
        state = self.reply(state, "its saying that password is wrong whenever i write my current password")
        self.assertEqual(self.step(state), "4")
        self.assertFalse(state["awaiting_confirmation"])
        self.assertEqual(state["facts"], {"error_type": "wrong_password"})
        state = self.reply(state, "ok, reset complete")
        self.assertEqual(self.step(state), "6")
        state = self.reply(state, "yes it works now")
        self.assertEqual(state["status"], "completed")

    def test_known_facts_in_issue_skip_questions(self):
        state = self.service.start_session("Login fails, the password is wrong")
        self.assertEqual(self.step(state), "4")
        self.assertIn("skip_known_step", state["trace"])
        self.assertIn("Already provided", state["context"][f"{self.runbook_id}_1"])

    def test_locked_account_requires_operator_confirmation(self):
        state = self.service.start_session("Cannot log in")
        state = self.reply(state, "it says account locked")
        self.assertEqual(self.step(state), "2")
        self.assertTrue(state["awaiting_confirmation"])
        self.assertIn("yes, no", state["messages"][-1]["message"])
        state = self.reply(state, "Operator: account is locked")
        self.assertEqual(self.step(state), "3")
        state = self.reply(state, "Unlocked per procedure")
        self.assertEqual(self.step(state), "6")

    def test_unclear_operator_result_is_clarified_once_then_escalated(self):
        state = self.service.start_session("Cannot log in")
        state = self.reply(state, "some other error")
        self.assertEqual(self.step(state), "1")
        self.assertIn("(one of: wrong_password", self.last_expected)
        state = self.reply(state, "still something else")
        self.assertEqual(self.step(state), "2")
        state = self.reply(state, "not sure")
        self.assertEqual(self.step(state), "2")
        self.assertIn("unclear", state["messages"][-1]["message"])
        self.assertNotIn(f"{self.runbook_id}_2", state["executed_steps"])
        state = self.reply(state, "still not sure")
        self.assertEqual(state["status"], "escalated")

    def test_customer_claim_does_not_satisfy_operator_check(self):
        state = self.service.start_session("Login says account locked; I think my account is locked")
        self.assertEqual(self.step(state), "2")
        state = self.reply(state, "checked")
        self.assertEqual(self.step(state), "2")
        self.assertNotIn("account_locked", state["facts"])

    def test_llm_receives_runbook_data_and_its_decision_is_logged(self):
        state = self.service.start_session("Cannot log in")
        state = self.reply(state, "its saying that password is wrong")
        call = self.decision_calls[-1]
        self.assertEqual(call["suggested_next_step"], f"{self.runbook_id}_4")
        self.assertEqual(call["facts"], {"error_type": "wrong_password"})
        self.assertIn("if error_type in ['wrong_password']", call["runbook_steps"])
        self.assertIn("Forgot Password", call["option_details"])
        decision = state["decisions"][-1]
        self.assertEqual(decision["next_step"], f"{self.runbook_id}_4")
        self.assertEqual(decision["reason"], "Evidence matches the rule.")

    def test_llm_can_override_rule_suggestion_within_approved_routes(self):
        service = self.make_service(step_reasoner=lambda **kwargs: {
            "next_step": f"{self.runbook_id}_2", "reason": "User mentions repeated lockouts.",
        })
        state = service.start_session("Cannot log in")
        state = service.submit_user_response(state["session_id"], "password is wrong, tried 10 times", 1)
        self.assertEqual(self.step(state), "2")
        self.assertEqual(state["decisions"][-1]["suggested"], f"{self.runbook_id}_4")

    def test_llm_cannot_choose_unapproved_destination(self):
        service = self.make_service(step_reasoner=lambda **kwargs: {"next_step": "END"})
        state = service.start_session("Cannot log in")
        with self.assertRaises(InvalidDecisionError):
            service.submit_user_response(state["session_id"], "password is wrong", 1)

    def test_fact_values_outside_options_are_dropped(self):
        service = self.make_service(fact_extractor=lambda **kwargs: {
            "error_type": "DROP TABLE", "login_works": "YES", "unknown": "x",
        })
        state = service.start_session("Cannot log in")
        self.assertEqual(state["facts"], {"login_works": "yes"})

    def test_legacy_schema_and_sessions_are_migrated(self):
        legacy_path = os.path.join(self.directory.name, "legacy.db")
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.executescript("""
                CREATE TABLE runbook_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, runbook_id TEXT,
                    step_order INTEGER, step_id TEXT, instruction TEXT, step_type TEXT
                );
                CREATE TABLE agent_sessions (
                    session_id TEXT PRIMARY KEY, user_issue TEXT NOT NULL, runbook_id TEXT NOT NULL,
                    status TEXT NOT NULL, current_step_id TEXT, executed_steps TEXT NOT NULL,
                    context_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                INSERT INTO agent_sessions VALUES
                ('legacy', 'Login error', 'TEST_LOGIN', 'active', 'TEST_LOGIN_1', '[]', '{}', 'now', 'now');
            """)
        with patch.dict(os.environ, {"RUNBOOK_DB_PATH": legacy_path}):
            initialize_database()
            insert_runbook(copy.deepcopy(RUNBOOK))
            state = self.service.get_session_state("legacy")
            self.assertEqual(state["version"], 0)
            self.assertEqual(state["current_step"]["step_id"], "TEST_LOGIN_1")
            state = self.service.submit_user_response("legacy", "Error reported", 0)
            self.assertEqual(state["version"], 1)


if __name__ == "__main__":
    unittest.main()
