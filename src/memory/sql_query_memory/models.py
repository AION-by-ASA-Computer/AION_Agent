"""DTOs for SQL QueryMemory API and tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SqlQueryHit(BaseModel):
    id: int
    user_request: str
    sql_text: str
    is_verified: bool
    success_count: int
    score: float
    project_slug: Optional[str] = None
    tables_used: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class SqlProjectOut(BaseModel):
    id: int
    slug: str
    display_name: str
    description: Optional[str] = None
    datasource_key: str
    profile_slug: Optional[str] = None
    scope_mode: str = "inherit"
    role: Optional[str] = None  # current user's role on this project


class SqlProjectMemberOut(BaseModel):
    user_identifier: str
    role: str
    invited_by: Optional[str] = None


class AdminProjectMemberOut(BaseModel):
    user_identifier: str
    role: str
    invited_by: Optional[str] = None
    created_at: datetime


class AdminProjectOut(BaseModel):
    id: int
    tenant_id: str
    slug: str
    display_name: str
    description: Optional[str] = None
    datasource_key: str
    profile_slug: Optional[str] = None
    scope_mode: str = "inherit"
    created_by: Optional[str] = None
    created_at: datetime
    members: List[AdminProjectMemberOut]


class TenantSqlQmSettingsOut(BaseModel):
    tenant_id: str
    sql_default_scope: str = "per_user"
    sql_auto_learn: bool = True
    sql_search_before_run: bool = True


class TenantSqlQmSettingsPatch(BaseModel):
    sql_default_scope: Optional[str] = None  # shared | per_user
    sql_auto_learn: Optional[bool] = None
    sql_search_before_run: Optional[bool] = None
