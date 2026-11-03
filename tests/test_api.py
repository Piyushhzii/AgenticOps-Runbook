import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.llm_gateway import LLMGatewayError
from tests.test_support_agent_service import IsolatedDatabaseTest


class ApiTest(IsolatedDatabaseTest):
    def setUp(self):
        super().setUp()
        service_patch = patch("app.main.agent_service", self.service)
        service_patch.start()
        self.addCleanup(service_patch.stop)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_api_round_trip_and_version_conflict(self):
        started = self.client.post("/sessions", json={"issue": "Cannot log in"})
        self.assertEqual(started.status_code, 200, started.text)
        state = started.json()
        url = f"/sessions/{state['session_id']}/responses"
        payload = {"message": "Login error", "expected_version": state["version"]}
        response = self.client.post(url, json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["awaiting_confirmation"])
        self.assertEqual(self.client.post(url, json=payload).status_code, 409)
        loaded = self.client.get(f"/sessions/{state['session_id']}")
        self.assertEqual(loaded.json()["version"], 2)

    def test_request_validation_and_missing_sessions(self):
        for issue in ("  ", "x" * 8001):
            self.assertEqual(self.client.post("/sessions", json={"issue": issue}).status_code, 422)
        self.assertEqual(
            self.client.post("/sessions/unknown/responses", json={"message": "Evidence"}).status_code, 422,
        )
        self.assertEqual(self.client.get("/sessions/unknown").status_code, 404)

    def test_api_key_guards_runbooks_sessions_and_readiness(self):
        with patch.dict(os.environ, {"OPS_API_KEY": "test-key-not-a-real-secret"}):
            for path in ("/runbooks", "/sessions/unknown", "/ready"):
                self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.post("/sessions", json={"issue": "Login error"}).status_code, 401)
            self.assertEqual(self.client.get("/health").status_code, 200)
            self.assertEqual(
                self.client.get("/runbooks", headers={"X-API-Key": "test-key-not-a-real-secret"}).status_code,
                200,
            )

    def test_production_fails_closed_without_key(self):
        with patch.dict(os.environ, {"OPS_ENV": "production", "OPS_API_KEY": ""}):
            self.assertEqual(self.client.get("/runbooks").status_code, 503)
            with self.assertRaisesRegex(RuntimeError, "OPS_API_KEY"):
                with TestClient(app):
                    pass

    def test_dependency_failure_has_explicit_sanitized_error(self):
        def fail(**kwargs):
            raise LLMGatewayError("provider detail")

        service = self.make_service(response_generator=fail)
        with patch("app.main.agent_service", service):
            response = self.client.post("/sessions", json={"issue": "Login error"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("provider detail", response.text)
        self.assertIn("turn was not saved", response.text)

    def test_readiness_checks_configuration_without_external_calls(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            response = self.client.get("/ready")
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json()["checks"]["llm_configured"])
        with patch.dict(os.environ, {"GROQ_API_KEY": "not-a-real-key"}):
            self.assertEqual(self.client.get("/ready").status_code, 200)
