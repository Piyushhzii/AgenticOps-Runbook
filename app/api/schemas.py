from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class StartSessionRequest(RequestModel):
    issue: str = Field(..., min_length=3, max_length=8000, description="Customer issue description")


class RespondRequest(RequestModel):
    message: str = Field(..., min_length=1, max_length=8000, description="Evidence for the current step")
    expected_version: int = Field(..., ge=0, strict=True, description="Version returned by the last session response")


class MessageRecord(BaseModel):
    role: str
    message: str
    step_id: Optional[str] = None
    created_at: str


class StepPayload(BaseModel):
    step_id: str
    step_order: int
    instruction: str
    step_type: str
    next_steps: Optional[List[str]] = None


class SessionResponse(BaseModel):
    session_id: str
    user_issue: str
    runbook_id: str
    status: str
    version: int
    awaiting_user_input: bool
    awaiting_confirmation: bool
    current_step: Optional[StepPayload] = None
    executed_steps: List[str]
    context: Dict[str, Any]
    facts: Dict[str, str] = Field(default_factory=dict)
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    messages: List[MessageRecord]
    trace: List[str]