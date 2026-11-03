from app.core.database import initialize_database
from app.repositories.sessions import SessionConflictError
from app.services.llm_gateway import LLMGatewayError
from app.services.support_agent import SupportAgentService
from app.services.support_agent import SupportAgentError


def _run_agent():
    initialize_database()
    agent_service = SupportAgentService()

    issue = input("Describe your issue: ")
    session_state = agent_service.start_session(issue)

    print(f"\nSelected Runbook: {session_state['runbook_id']}")

    while session_state["status"] == "active":
        current_step = session_state["current_step"]
        if not current_step:
            break

        print(f"\n{session_state['messages'][-1]['message']}")
        print(f"STEP: {current_step['instruction']}")

        if session_state["awaiting_user_input"]:
            user_input = input("User: ")
            if user_input.lower() == "exit":
                print("\nRunbook exited.")
                return
            session_state = agent_service.submit_user_response(
                session_state["session_id"], user_input,
                expected_version=session_state["version"],
            )
            continue

        session_state = agent_service.get_session_state(session_state["session_id"])

    print(f"\n{session_state['messages'][-1]['message']}")


def run_agent():
    try:
        _run_agent()
    except (SupportAgentError, LLMGatewayError, SessionConflictError, ValueError) as exc:
        raise SystemExit(f"Agent failed: {exc}") from exc


if __name__ == "__main__":
    run_agent()