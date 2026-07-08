"""Pydantic models for cron job HTTP APIs."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

SessionMode = Literal["fixed", "new"]


class ScheduledJobCreate(BaseModel):
    name: str
    cron_expression: str
    prompt: str
    profile_slug: str = "generic_assistant"
    session_mode: SessionMode = "fixed"
    session_id: Optional[str] = None
    sql_query_project: Optional[str] = None
    timezone: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True
    agent_mode: str = "normal"


class ScheduledJobUpdate(BaseModel):
    name: Optional[str] = None
    cron_expression: Optional[str] = None
    prompt: Optional[str] = None
    profile_slug: Optional[str] = None
    session_mode: Optional[SessionMode] = None
    session_id: Optional[str] = None
    sql_query_project: Optional[str] = None
    timezone: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    agent_mode: Optional[str] = None


class ScheduledJobOut(BaseModel):
    job_id: str
    tenant_id: str
    user_id: str
    name: str
    description: Optional[str] = None
    cron_expression: str
    timezone: str
    profile_slug: str
    prompt: str
    session_mode: str
    session_id: Optional[str] = None
    sql_query_project: Optional[str] = None
    enabled: bool
    agent_mode: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_by: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    next_run_at: Optional[str] = None
    last_run: Optional[Dict[str, Any]] = None


class ScheduledJobListResponse(BaseModel):
    jobs: List[ScheduledJobOut]
    total: int


class ScheduledRunOut(BaseModel):
    run_id: str
    job_id: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    status: str
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    error_message: Optional[str] = None
    assistant_preview: Optional[str] = None


class ScheduledRunListResponse(BaseModel):
    runs: List[ScheduledRunOut]
