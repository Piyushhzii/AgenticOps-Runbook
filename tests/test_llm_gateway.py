import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from groq import APITimeoutError
from pydantic import ValidationError

from app.services import llm_gateway
from tests.test_support_agent_service import RUNBOOK


class LLMGatewayTest(unittest.TestCase):
    def test_missing_api_key_is_explicit(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            with self.assertRaisesRegex(llm_gateway.LLMGatewayError, "not configured"):
                llm_gateway._build_llm()

    def test_model_calls_are_bounded(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "not-a-real-key"}):
            with patch.object(llm_gateway, "ChatGroq") as model:
                llm_gateway._build_llm()
        self.assertEqual(model.call_args.kwargs["timeout"], 30)
        self.assertEqual(model.call_args.kwargs["max_retries"], 2)
        self.assertEqual(model.call_args.kwargs["max_tokens"], 4096)

    def test_provider_failure_is_not_a_success_fallback(self):
        model = Mock()
        model.invoke.side_effect = APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
        with patch.object(llm_gateway, "_build_llm", return_value=model):
            with self.assertRaisesRegex(llm_gateway.LLMGatewayError, "provider request failed"):
                llm_gateway._invoke("Test prompt")

    def test_invalid_or_empty_provider_content_is_rejected(self):
        for content in ("", "  ", []):
            model = Mock()
            model.invoke.return_value = SimpleNamespace(content=content)
            with patch.object(llm_gateway, "_build_llm", return_value=model):
                with self.assertRaises(llm_gateway.LLMGatewayError):
                    llm_gateway._invoke("Test prompt")

    def test_prompt_budget_is_enforced_before_provider_call(self):
        with patch.object(llm_gateway, "_build_llm") as model:
            with self.assertRaisesRegex(llm_gateway.LLMGatewayError, "budget"):
                llm_gateway._invoke("x" * 48001)
            model.assert_not_called()

    def test_invalid_branch_is_not_silently_replaced(self):
        with patch.object(llm_gateway, "_invoke", return_value="END"):
            with self.assertRaises(llm_gateway.LLMGatewayError):
                llm_gateway.decide_next_step("steps", "one", "evidence", [], {}, ["two"])

    def test_step_decision_returns_reason(self):
        reply = '```json\n{"next_step": "two", "reason": "Status is failed."}\n```'
        with patch.object(llm_gateway, "_invoke", return_value=reply):
            result = llm_gateway.decide_next_step("steps", "one", "evidence", [], {}, ["two", "ESCALATE"])
        self.assertEqual(result, {"next_step": "two", "reason": "Status is failed."})

    def test_runbook_extraction_requires_valid_json_and_schema(self):
        with patch.object(llm_gateway, "_invoke", return_value="not json"):
            with self.assertRaises(llm_gateway.LLMGatewayError):
                llm_gateway.extract_runbook("source")
        with patch.object(llm_gateway, "_invoke", return_value='{"steps": []}'):
            with self.assertRaises(ValidationError):
                llm_gateway.extract_runbook("source")
        with patch.object(llm_gateway, "_invoke", return_value=json.dumps(RUNBOOK)):
            self.assertEqual(len(llm_gateway.extract_runbook("source")["steps"]), 3)

    def test_extracted_routes_are_repaired(self):
        runbook = {
            "runbook_name": "Login", "issue_category": "Auth", "description": "Login help",
            "facts": [{"name": "locked", "description": "Locked?", "options": ["yes", "no"]}],
            "steps": [
                {"step_id": "a", "step_order": 1, "instruction": "Check", "step_type": "message",
                 "collects": "locked", "routes": [
                     {"to": "ESCALATE"},
                     {"when": {"locked": "yes"}, "to": "b"},
                     {"when": {}, "to": "END"},
                 ]},
                {"step_id": "b", "step_order": 2, "instruction": "Unlock", "step_type": "message",
                 "routes": [{"when": {"locked": "yes"}, "to": "END"}]},
            ],
        }
        with patch.object(llm_gateway, "_invoke", return_value=json.dumps(runbook)) as invoke:
            steps = llm_gateway.extract_runbook("source")["steps"]
        invoke.assert_called_once()
        self.assertEqual([route["to"] for route in steps[0]["routes"]], ["b", "ESCALATE"])
        self.assertEqual(steps[1]["routes"][-1], {"when": {}, "to": "ESCALATE"})

    def test_extraction_self_corrects_once_with_validation_feedback(self):
        with patch.object(llm_gateway, "_invoke", side_effect=['{"steps": []}', json.dumps(RUNBOOK)]) as invoke:
            self.assertEqual(len(llm_gateway.extract_runbook("source")["steps"]), 3)
        self.assertIn("failed validation", invoke.call_args_list[1].args[0])
