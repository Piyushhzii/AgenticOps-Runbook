import logging
from typing import Callable, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.core.runbooks import RunbookDefinition, Route, Step
from app.repositories.runbooks import get_all_runbooks, get_fact_definitions, get_steps
from app.repositories.sessions import (
    Message, SessionConflictError, SessionRecord, new_message, read_session, save_turn,
)
from app.services.llm_gateway import (
    decide_next_step, extract_facts, generate_support_response, select_runbook,
)

logger = logging.getLogger(__name__)


class SupportAgentError(Exception):
    pass


class SessionNotFoundError(SupportAgentError):
    pass


class RunbookResolutionError(SupportAgentError):
    pass


class InvalidDecisionError(SupportAgentError):
    pass


class SessionInactiveError(SupportAgentError):
    pass


class GraphState(TypedDict):
    issue: str
    session: SessionRecord | None
    user_message: str | None
    history: list[Message]
    pending: list[Message]
    trace: list[str]
    clarify: bool


MAX_CLARIFICATIONS = 1
ASK_AGAIN = "ASK_AGAIN"
_TERMINAL_MEANING = {
    "END": "Issue is resolved and verified; close the runbook.",
    "ESCALATE": "Hand off to human support with the collected evidence.",
    ASK_AGAIN: "The latest reply does not give enough evidence for this step; ask it again more specifically.",
}


def _session(state: GraphState) -> SessionRecord:
    session = state["session"]
    if session is None:
        raise SupportAgentError("Graph session has not been initialized")
    return session


def normalize_facts(definitions: list[dict], raw: dict) -> dict[str, str]:
    by_name = {definition["name"]: definition for definition in definitions}
    facts = {}
    for name, value in raw.items():
        definition = by_name.get(name)
        if definition is None or value is None or not str(value).strip():
            continue
        text = str(value).strip()[:500]
        if definition.get("options"):
            text = next((option for option in definition["options"] if option.lower() == text.lower()), "")
        if text:
            facts[name] = text
    return facts


def suggest_route(routes: list[Route], facts: dict[str, str]) -> str | None:
    """Return the first conditional route satisfied by known facts, ignoring the otherwise route."""
    for route in routes:
        if route["when"] and all(facts.get(name) in values for name, values in route["when"].items()):
            return route["to"]
    return None


def describe_step(step_id: str, step: Step) -> str:
    text = f"{step_id} [{step['step_type']}]: {step['instruction']}"
    if step.get("collects"):
        text += f"\n    collects: {step['collects']}"
    for route in step.get("routes") or []:
        condition = " and ".join(
            f"{name} in {values}" for name, values in route["when"].items()
        ) or "otherwise"
        text += f"\n    if {condition} -> {route['to']}"
    return text


class SupportAgentService:
    def __init__(
        self,
        runbook_selector: Callable[[str], str] | None = None,
        step_reasoner: Callable[..., str | dict] | None = None,
        response_generator: Callable[..., str] | None = None,
        fact_extractor: Callable[..., dict] | None = None,
    ):
        self.runbook_selector = runbook_selector or self._select_runbook
        self.step_reasoner = step_reasoner or decide_next_step
        self.response_generator = response_generator or generate_support_response
        self.fact_extractor = fact_extractor or extract_facts
        graph = StateGraph(GraphState)
        graph.add_node("select_runbook", self._select_node)
        graph.add_node("inspect_step", self._inspect_node)
        graph.add_node("collect_evidence", self._collect_node)
        graph.add_node("skip_known_step", self._skip_node)
        graph.add_node("route_step", self._route_node)
        graph.add_node("respond", self._respond_node)
        graph.add_conditional_edges(
            START, lambda state: "select_runbook" if state["session"] is None else "inspect_step",
            {"select_runbook": "select_runbook", "inspect_step": "inspect_step"},
        )
        graph.add_edge("select_runbook", "inspect_step")
        graph.add_conditional_edges(
            "inspect_step", self._after_inspect,
            {"collect_evidence": "collect_evidence", "skip_known_step": "skip_known_step", "respond": "respond"},
        )
        graph.add_edge("collect_evidence", "route_step")
        graph.add_edge("skip_known_step", "route_step")
        graph.add_edge("route_step", "inspect_step")
        graph.add_edge("respond", END)
        self.graph = graph.compile()

    def list_runbooks(self) -> list[dict[str, str]]:
        return get_all_runbooks()

    def start_session(self, user_issue: str) -> dict:
        issue = self._validate_text(user_issue, 3)
        return self._run_turn(
            GraphState(
                issue=issue, session=None, user_message=None, history=[], pending=[], trace=[],
                clarify=False,
            ),
            is_new=True,
        )

    def submit_user_response(
        self, session_id: str, user_message: str, expected_version: int | None = None,
    ) -> dict:
        message = self._validate_text(user_message, 1)
        session, history = self._load_session(session_id)
        if expected_version is not None and session["version"] != expected_version:
            raise SessionConflictError("Stale session version; reload before responding.")
        if session["status"] != "active":
            raise SessionInactiveError("Session is closed; start a new session.")
        return self._run_turn(
            GraphState(
                issue=session["user_issue"], session=session, user_message=message,
                history=history, pending=[], trace=[], clarify=False,
            ),
            is_new=False,
        )

    def get_session_state(self, session_id: str) -> dict:
        session, history = self._load_session(session_id)
        return self._build_state_response(session, history, [])

    def _select_runbook(self, user_issue: str) -> str:
        return select_runbook(user_issue, self.list_runbooks())

    @staticmethod
    def _validate_text(text: str, minimum: int) -> str:
        text = text.strip()
        if not minimum <= len(text) <= 8000:
            raise ValueError(f"Text must contain between {minimum} and 8000 characters")
        return text

    def _load_session(self, session_id: str) -> tuple[SessionRecord, list[Message]]:
        snapshot = read_session(session_id)
        if snapshot is None:
            raise SessionNotFoundError(f"Unknown session: {session_id}")
        session, history = snapshot
        if not session["steps"]:
            session["steps"] = get_steps(session["runbook_id"])
            session["fact_definitions"] = get_fact_definitions(session["runbook_id"])
        self._validate_steps(session["steps"], session["fact_definitions"])
        if session["status"] == "active" and session["current_step_id"] not in session["steps"]:
            raise RunbookResolutionError("Session references a missing step")
        return session, history

    @staticmethod
    def _validate_steps(steps: dict[str, Step], fact_definitions: list[dict]) -> None:
        RunbookDefinition.model_validate({
            "runbook_name": "Session snapshot", "issue_category": "operations",
            "description": "Validated runbook snapshot", "facts": fact_definitions,
            "steps": [{"step_id": step_id, **step} for step_id, step in steps.items()],
        })

    def _extract(self, session: SessionRecord, message: str, question: str) -> dict[str, str]:
        if not session["fact_definitions"]:
            return {}
        raw = self.fact_extractor(
            message=message, fact_definitions=session["fact_definitions"],
            known_facts=session["facts"], current_question=question,
        )
        return normalize_facts(session["fact_definitions"], raw)

    def _select_node(self, state: GraphState) -> dict:
        runbook_id = self.runbook_selector(state["issue"]).strip()
        if runbook_id not in {item["runbook_id"] for item in self.list_runbooks()}:
            raise RunbookResolutionError("No matching runbook; operator triage is required.")
        steps = get_steps(runbook_id)
        if not steps:
            raise RunbookResolutionError(f"No steps found for runbook: {runbook_id}")
        fact_definitions = get_fact_definitions(runbook_id)
        self._validate_steps(steps, fact_definitions)
        first = min(steps, key=lambda step_id: steps[step_id]["step_order"])
        session = SessionRecord(
            session_id=str(uuid4()), user_issue=state["issue"], runbook_id=runbook_id,
            status="active", current_step_id=first, executed_steps=[], context={}, version=0,
            steps=steps, fact_definitions=fact_definitions, facts={}, attempts={}, decisions=[],
        )
        session["facts"] = self._extract(session, state["issue"], "Initial issue description")
        return {
            "session": session, "pending": [new_message("user", state["issue"])],
            "trace": [*state["trace"], "select_runbook"],
        }

    def _inspect_node(self, state: GraphState) -> dict:
        return {"trace": [*state["trace"], "inspect_step"]}

    @staticmethod
    def _known_fact(session: SessionRecord) -> str | None:
        step_id = session["current_step_id"]
        if session["status"] != "active" or step_id is None or step_id in session["executed_steps"]:
            return None
        step = session["steps"][step_id]
        fact = step.get("collects")
        # Operator checks are never skipped on the strength of customer statements.
        if step["step_type"] == "input" and fact and fact in session["facts"]:
            return fact
        return None

    def _after_inspect(self, state: GraphState) -> str:
        if state["user_message"] is not None:
            return "collect_evidence"
        if not state["clarify"] and self._known_fact(_session(state)):
            return "skip_known_step"
        return "respond"

    def _skip_node(self, state: GraphState) -> dict:
        session = _session(state)
        step_id = session["current_step_id"]
        fact = self._known_fact(session)
        if step_id is None or fact is None:
            raise InvalidDecisionError("Only steps with an already-known fact can be skipped")
        session["context"][step_id] = f"Already provided: {fact} = {session['facts'][fact]}"
        session["executed_steps"].append(step_id)
        return {"session": session, "trace": [*state["trace"], "skip_known_step"]}

    def _collect_node(self, state: GraphState) -> dict:
        session = _session(state)
        step_id = session["current_step_id"]
        message = state["user_message"]
        if step_id is None or message is None:
            raise InvalidDecisionError("Cannot collect evidence without an active step and response")
        if step_id in session["executed_steps"]:
            raise InvalidDecisionError("A completed step cannot execute again")
        pending = [*state["pending"], new_message("user", message, step_id)]
        if message.lower() == "/escalate":
            session["status"] = "escalated"
            session["current_step_id"] = None
        else:
            step = session["steps"][step_id]
            fact = step.get("collects")
            if fact and step["step_type"] == "message":
                session["facts"].pop(fact, None)
            session["facts"].update(self._extract(session, message, step["instruction"]))
            if fact and fact not in session["facts"]:
                definition = next(item for item in session["fact_definitions"] if item["name"] == fact)
                if not definition.get("options"):
                    session["facts"][fact] = message[:500]
            # Evidence is operator-reported, never an inferred external system result.
            session["context"][step_id] = message
            session["executed_steps"].append(step_id)
        return {
            "session": session, "pending": pending, "user_message": None, "clarify": False,
            "trace": [*state["trace"], "collect_evidence"],
        }

    def _route_node(self, state: GraphState) -> dict:
        session = _session(state)
        step_id = session["current_step_id"]
        clarify = False
        if session["status"] == "active" and step_id is not None:
            steps = session["steps"]
            step = steps[step_id]
            ordered_ids = sorted(steps, key=lambda key: steps[key]["step_order"])
            index = ordered_ids.index(step_id)
            suggested = None
            if step.get("routes"):
                targets = list(dict.fromkeys(route["to"] for route in step["routes"] or []))
                suggested = suggest_route(step["routes"] or [], session["facts"])
            else:
                targets = step["next_steps"]
                if targets is None:
                    targets = [ordered_ids[index + 1]] if index + 1 < len(ordered_ids) else ["END"]
            allowed = [
                target for target in targets
                if target in {"END", "ESCALATE"} or target not in session["executed_steps"]
            ]
            if not allowed:
                raise InvalidDecisionError("No valid destination remains")
            fact = step.get("collects")
            if (
                fact and fact not in session["facts"]
                and session["attempts"].get(step_id, 0) < MAX_CLARIFICATIONS
            ):
                allowed.append(ASK_AGAIN)
            next_step, reason = allowed[0], "Only one approved destination."
            if len(allowed) > 1:
                next_step, reason = self._decide(session, step_id, allowed, suggested)
            if next_step not in allowed:
                raise InvalidDecisionError("LLM selected a destination outside the approved routes")
            session["decisions"].append({
                "step_id": step_id, "next_step": next_step, "suggested": suggested,
                "reason": reason, "options": allowed,
            })
            if next_step == ASK_AGAIN:
                session["executed_steps"].remove(step_id)
                session["attempts"][step_id] = session["attempts"].get(step_id, 0) + 1
                clarify = True
            else:
                self._advance(session, next_step)
        return {"session": session, "clarify": clarify, "trace": [*state["trace"], "route_step"]}

    def _decide(
        self, session: SessionRecord, step_id: str, allowed: list[str], suggested: str | None,
    ) -> tuple[str, str]:
        steps = session["steps"]
        options = "\n".join(
            f"- {target}: {_TERMINAL_MEANING.get(target) or steps[target]['instruction']}"
            for target in allowed
        )
        result = self.step_reasoner(
            runbook_steps="\n".join(describe_step(key, value) for key, value in steps.items()),
            current_step=describe_step(step_id, steps[step_id]),
            user_response=session["context"].get(step_id, ""),
            executed_steps=session["executed_steps"], context=session["context"],
            allowed_next_steps=allowed, option_details=options,
            facts=session["facts"], suggested_next_step=suggested,
        )
        if isinstance(result, dict):
            return str(result.get("next_step", "")).strip(), str(result.get("reason", ""))[:500]
        return str(result).strip(), ""

    @staticmethod
    def _advance(session: SessionRecord, next_step: str) -> None:
        if next_step in {"END", "ESCALATE"}:
            session["status"] = "completed" if next_step == "END" else "escalated"
            session["current_step_id"] = None
        elif next_step in session["steps"] and next_step not in session["executed_steps"]:
            session["current_step_id"] = next_step
        else:
            raise InvalidDecisionError(f"Route destination {next_step} is not available")

    @staticmethod
    def _expected_answer(session: SessionRecord, step: Step) -> str:
        fact = step.get("collects")
        definition = next(
            (item for item in session["fact_definitions"] if item["name"] == fact), None,
        )
        if definition is None:
            return ""
        options = definition.get("options")
        return f"{definition['description']}" + (f" (one of: {', '.join(options)})" if options else "")

    def _respond_node(self, state: GraphState) -> dict:
        session = _session(state)
        step_id = session["current_step_id"]
        if session["status"] == "completed":
            reply = "Runbook completed. This does not independently verify resolution. Start a new session if help is still needed."
        elif session["status"] == "escalated":
            reply = "Operator handoff required. Collected evidence is saved in this session. No external ticket has been created."
        else:
            if step_id is None:
                raise InvalidDecisionError("Active session has no current step")
            step = session["steps"][step_id]
            expected = self._expected_answer(session, step)
            if step["step_type"] == "message":
                prefix = "That result was unclear. " if state["clarify"] else ""
                report = f"Report: {expected}." if expected else "Report the actual result."
                reply = (
                    f"{prefix}Operator action needed (no system action has been executed by this copilot):\n"
                    f"{step['instruction']}\n\n"
                    f"An authorized operator should perform this and reply here. {report} "
                    "Enter /escalate to hand off. Never share passwords, codes, or full card details."
                )
            else:
                reply = self.response_generator(
                    user_issue=session["user_issue"], runbook_id=session["runbook_id"],
                    current_step=step, context=session["context"],
                    message_history=[*state["history"], *state["pending"]], status=session["status"],
                    facts=session["facts"], expected_answer=expected,
                ).strip()
                if not reply:
                    raise InvalidDecisionError("Response generator returned an empty message")
        return {
            "pending": [*state["pending"], new_message("assistant", reply, step_id)],
            "trace": [*state["trace"], "respond"],
        }

    def _run_turn(self, state: GraphState, *, is_new: bool) -> dict:
        # Each skipped step costs three graph hops; runbooks are capped at 100 steps.
        result = self.graph.invoke(state, config={"recursion_limit": 320})
        session = result["session"]
        if session is None:
            raise SupportAgentError("Graph completed without a session")
        session["version"] = save_turn(session, result["pending"], is_new=is_new)
        logger.info(
            "agent_turn session_id=%s version=%s status=%s nodes=%s",
            session["session_id"], session["version"], session["status"], result["trace"],
        )
        return self._build_state_response(
            session, [*state["history"], *result["pending"]], result["trace"],
        )

    @staticmethod
    def _build_state_response(
        session: SessionRecord, messages: list[Message], trace: list[str],
    ) -> dict:
        step_id = session["current_step_id"]
        step = session["steps"].get(step_id) if step_id else None
        return {
            "session_id": session["session_id"], "user_issue": session["user_issue"],
            "runbook_id": session["runbook_id"], "status": session["status"],
            "version": session["version"],
            "awaiting_user_input": session["status"] == "active",
            "awaiting_confirmation": bool(step and step["step_type"] == "message"),
            "current_step": {"step_id": step_id, **step} if step else None,
            "executed_steps": session["executed_steps"], "context": session["context"],
            "facts": session["facts"], "decisions": session["decisions"],
            "messages": messages, "trace": trace,
        }
