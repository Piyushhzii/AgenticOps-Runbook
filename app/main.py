import logging
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from app.api.schemas import RespondRequest, SessionResponse, StartSessionRequest
from app.core.database import database_transaction, initialize_database
from app.repositories.sessions import SessionConflictError
from app.services.llm_gateway import LLMGatewayError
from app.services.support_agent import (
    InvalidDecisionError, RunbookResolutionError, SessionInactiveError,
    SessionNotFoundError, SupportAgentService,
)

logger = logging.getLogger(__name__)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Depends(api_key_header)) -> None:
    expected = os.getenv("OPS_API_KEY")
    if expected and (key is None or not secrets.compare_digest(key.encode(), expected.encode())):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    if not expected and os.getenv("OPS_ENV", "development") != "development":
        raise HTTPException(status_code=503, detail="API authentication is not configured")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    environment = os.getenv("OPS_ENV", "development")
    if environment != "development" and not os.getenv("OPS_API_KEY"):
        raise RuntimeError("OPS_API_KEY is required outside development")
    if not os.getenv("OPS_API_KEY"):
        logger.warning("Development mode: API authentication is disabled; bind to loopback only")
    initialize_database()
    yield


app = FastAPI(
    title="Agentic Operations Runbook API",
    version="2.0.0",
    description="Human-in-the-loop LangGraph runbook orchestration; no external actions are executed.",
    lifespan=lifespan,
)
agent_service = SupportAgentService()


@app.exception_handler(SessionNotFoundError)
@app.exception_handler(RunbookResolutionError)
@app.exception_handler(SessionConflictError)
@app.exception_handler(SessionInactiveError)
@app.exception_handler(InvalidDecisionError)
@app.exception_handler(LLMGatewayError)
async def agent_error_handler(request: Request, exc: Exception):
    if isinstance(exc, (SessionNotFoundError, RunbookResolutionError)):
        code = 404
    elif isinstance(exc, (SessionConflictError, SessionInactiveError)):
        code = 409
    else:
        code = 502
    logger.warning("agent_request_failed type=%s status=%s", type(exc).__name__, code)
    detail = str(exc) if code < 500 else "Agent dependency or routing failed; the turn was not saved."
    return JSONResponse(status_code=code, content={"detail": detail})


@app.exception_handler(sqlite3.OperationalError)
async def database_error_handler(request: Request, exc: sqlite3.OperationalError):
    logger.error("database_operation_failed type=%s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable; retry later."})


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/ready", dependencies=[Depends(require_api_key)])
def readiness_check():
    with database_transaction() as connection:
        connection.execute("SELECT version, steps_json FROM agent_sessions LIMIT 1").fetchone()
    checks = {
        "database": True,
        "runbooks": bool(agent_service.list_runbooks()),
        "llm_configured": bool(os.getenv("GROQ_API_KEY")),
    }
    if not all(checks.values()):
        return JSONResponse(status_code=503, content={"status": "not_ready", "checks": checks})
    return {"status": "ready", "checks": checks}


@app.get("/runbooks", dependencies=[Depends(require_api_key)])
def list_runbooks():
    return {"items": agent_service.list_runbooks()}


@app.post("/sessions", response_model=SessionResponse, dependencies=[Depends(require_api_key)])
def start_session(request: StartSessionRequest):
    return agent_service.start_session(request.issue)


@app.get("/sessions/{session_id}", response_model=SessionResponse, dependencies=[Depends(require_api_key)])
def get_session(session_id: str):
    return agent_service.get_session_state(session_id)


@app.post("/sessions/{session_id}/responses", response_model=SessionResponse, dependencies=[Depends(require_api_key)])
def respond_to_session(session_id: str, request: RespondRequest):
    return agent_service.submit_user_response(
        session_id, request.message, expected_version=request.expected_version,
    )


def run_api():
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
