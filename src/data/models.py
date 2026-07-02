"""Unified aion.db ORM (subset used by chat history + v1 API)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    LargeBinary,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    metadata_json: Mapped[str] = mapped_column("metadata", Text, default="{}")


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id"), nullable=False
    )
    identifier: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(256))
    email: Mapped[Optional[str]] = mapped_column(String(256))
    password_hash: Mapped[Optional[str]] = mapped_column(String(256))
    metadata_json: Mapped[str] = mapped_column("metadata", Text, default="{}")
    # JSON list di ruoli (es. ["admin"]). Default vuoto. Verificare con
    # ``user_password.has_role(u, "admin")`` invece di parsing inline.
    roles_json: Mapped[str] = mapped_column(
        "roles", Text, default="[]", server_default="[]", nullable=False
    )
    # Stile Grafana: True dopo creazione admin di default; il client mostra
    # un banner non-bloccante per cambiare la password al primo accesso.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("tenant_id", "identifier", name="uq_users_tenant_identifier"),
    )


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    hash: Mapped[str] = mapped_column(String(256), nullable=False)
    scopes_json: Mapped[str] = mapped_column("scopes", Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id"), nullable=False, default="default"
    )
    user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    profile_slug: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[str] = mapped_column("metadata", Text, default="{}")
    tags_json: Mapped[str] = mapped_column("tags", Text, default="[]")

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"
    fts_rowid: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    timeline_json: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    tool_name: Mapped[Optional[str]] = mapped_column(String(256))
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(128))
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer)
    finish_reason: Mapped[Optional[str]] = mapped_column(String(64))
    promoted_to_ltm: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    profile_name: Mapped[str] = mapped_column(String(256), default="default")
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_msg_conv_seq"),
    )


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    message_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("messages.id", ondelete="SET NULL")
    )
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str] = mapped_column(String(256), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Step(Base):
    __tablename__ = "steps"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[Optional[str]] = mapped_column(String(64))
    message_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("messages.id", ondelete="SET NULL")
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    input: Mapped[Optional[str]] = mapped_column(Text)
    output: Mapped[Optional[str]] = mapped_column(Text)
    is_error: Mapped[int] = mapped_column(Integer, default=0)
    streaming: Mapped[int] = mapped_column(Integer, default=0)
    wait_for_answer: Mapped[Optional[int]] = mapped_column(Integer)
    start: Mapped[Optional[str]] = mapped_column(Text)
    end: Mapped[Optional[str]] = mapped_column(Text)
    indent: Mapped[Optional[int]] = mapped_column(Integer)
    metadata_json: Mapped[Optional[str]] = mapped_column("metadata", Text)
    tags_json: Mapped[Optional[str]] = mapped_column("tags", Text)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Feedback(Base):
    __tablename__ = "feedbacks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("messages.id"), nullable=True
    )
    step_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("steps.id", ondelete="CASCADE"), nullable=True
    )
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(128))
    resource_id: Mapped[Optional[str]] = mapped_column(String(256))
    payload: Mapped[Optional[str]] = mapped_column(Text)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ApprovalRule(Base):
    __tablename__ = "approval_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(String(256))
    tool_name: Mapped[str] = mapped_column(String(256), nullable=False)
    input_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    rationale: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    uses: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class CachedQuery(Base):
    __tablename__ = "cached_queries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_request: Mapped[str] = mapped_column(Text, nullable=False)
    promql_query: Mapped[str] = mapped_column(Text, nullable=False)
    is_verified: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    namespace: Mapped[str] = mapped_column(String(128), default="default")
    metadata_json: Mapped[Optional[str]] = mapped_column("metadata", Text)
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_request", "namespace", name="uq_cached_query_request_ns"
        ),
    )


class TenantQueryMemorySettings(Base):
    __tablename__ = "tenant_query_memory_settings"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sql_default_scope: Mapped[str] = mapped_column(
        String(16), default="per_user", server_default="per_user"
    )
    sql_auto_learn: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1"
    )
    sql_search_before_run: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SqlQueryProject(Base):
    __tablename__ = "sql_query_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    datasource_key: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default"
    )
    profile_slug: Mapped[Optional[str]] = mapped_column(String(256))
    scope_mode: Mapped[str] = mapped_column(
        String(16), default="inherit", server_default="inherit"
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_sql_query_project_tenant_slug"),
    )

    members: Mapped[list["SqlQueryProjectMember"]] = relationship(
        "SqlQueryProjectMember",
        back_populates="project",
        cascade="all, delete-orphan",
    )


class SqlQueryProjectMember(Base):
    __tablename__ = "sql_query_project_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sql_query_projects.id", ondelete="CASCADE"), nullable=False
    )
    user_identifier: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="member", server_default="member"
    )
    invited_by: Mapped[Optional[str]] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["SqlQueryProject"] = relationship(
        "SqlQueryProject", back_populates="members"
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_identifier", name="uq_sql_query_project_member"
        ),
    )


class CachedSqlQuery(Base):
    __tablename__ = "cached_sql_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sql_query_projects.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    user_id: Mapped[Optional[str]] = mapped_column(String(256))
    user_scope_key: Mapped[str] = mapped_column(String(256), nullable=False)
    user_request: Mapped[str] = mapped_column(Text, nullable=False)
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    sql_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_request: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    embedding_sql: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    tables_used_json: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[Optional[str]] = mapped_column("metadata", Text)
    is_verified: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "user_scope_key",
            "sql_fingerprint",
            name="uq_cached_sql_project_scope_fp",
        ),
    )


class TrustedPath(Base):
    __tablename__ = "trusted_paths"
    path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_name: Mapped[str] = mapped_column(String(256), nullable=False)
    profile_name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    overall_score: Mapped[Optional[float]] = mapped_column(
        Integer
    )  # scaled to float logic
    metadata_json: Mapped[str] = mapped_column("metadata", Text, default="{}")


class EvalResult(Base):
    __tablename__ = "eval_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(String(256), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_output: Mapped[Optional[str]] = mapped_column(Text)
    actual_output: Mapped[Optional[str]] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Integer, nullable=False)
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    latency_sec: Mapped[Optional[float]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExecutionPlanRecord(Base):
    """Piano orchestrazione (draft / approvato / rifiutato)."""

    __tablename__ = "execution_plans"
    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    draft_json: Mapped[str] = mapped_column(Text, nullable=False)
    draft_markdown: Mapped[Optional[str]] = mapped_column(Text)
    approved_json: Mapped[Optional[str]] = mapped_column(Text)
    approved_markdown: Mapped[Optional[str]] = mapped_column(Text)
    annotations_json: Mapped[Optional[str]] = mapped_column("annotations", Text)
    todos_json: Mapped[Optional[str]] = mapped_column("todos", Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    audit_meta_json: Mapped[Optional[str]] = mapped_column("audit_meta", Text)


class OrchestrationAudit(Base):
    """Audit approve/reject / timeout piani."""

    __tablename__ = "orchestration_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SecurityScan(Base):
    """Storico delle scansioni di sicurezza statiche (Antivirus)."""

    __tablename__ = "security_scans"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    target_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_safe: Mapped[bool] = mapped_column(Boolean, nullable=False)
    results_json: Mapped[str] = mapped_column("results", Text, nullable=False)


class McpServerConfig(Base):
    """Admin: quali server MCP sono esposti agli utenti e schema credenziali."""

    __tablename__ = "mcp_server_configs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    server_slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    icon_url: Mapped[Optional[str]] = mapped_column(String(512))
    is_enabled_for_users: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    requires_user_credentials: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # none | org_shared | per_user — allineato al catalogo connettori e registry env
    credential_mode: Mapped[str] = mapped_column(
        String(32), default="none", nullable=False
    )
    aion_connector_id: Mapped[Optional[str]] = mapped_column(String(64))
    user_may_disable: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    credential_schema_json: Mapped[Optional[str]] = mapped_column(
        "credential_schema", Text
    )
    oauth_config_json: Mapped[Optional[str]] = mapped_column("oauth_config", Text)
    category: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserMcpPreference(Base):
    """Preferenza utente: integrazione MCP opzionale attiva/disattiva."""

    __tablename__ = "user_mcp_preferences"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    server_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "tenant_id",
            "server_slug",
            name="uq_user_mcp_preference",
        ),
    )


class ScheduledJob(Base):
    """Cron job per-utente (prompt ricorrente verso l'agente)."""

    __tablename__ = "scheduled_jobs"
    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default", index=True
    )
    user_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    cron_expression: Mapped[str] = mapped_column(String(128), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    profile_slug: Mapped[str] = mapped_column(String(256), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    session_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="fixed"
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    agent_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="normal"
    )
    metadata_json: Mapped[Optional[str]] = mapped_column("metadata", Text)
    created_by: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    next_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), index=True
    )

    runs: Mapped[list["ScheduledJobRun"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class ScheduledJobRun(Base):
    """Esecuzione di un scheduled job."""

    __tablename__ = "scheduled_job_runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("scheduled_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(128))
    conversation_id: Mapped[Optional[str]] = mapped_column(String(128))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    assistant_preview: Mapped[Optional[str]] = mapped_column(Text)

    job: Mapped["ScheduledJob"] = relationship(back_populates="runs")


class UserMcpCredential(Base):
    """Credenziali MCP per utente (valore cifrato)."""

    __tablename__ = "user_mcp_credentials"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    server_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    credential_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    display_hint: Mapped[Optional[str]] = mapped_column(String(128))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "tenant_id",
            "server_slug",
            "credential_key",
            name="uq_user_mcp_credential",
        ),
    )


class LlmProvider(Base):
    """Provider LLM configurabile (multi-tenant, multi-model)."""

    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    icon_url: Mapped[Optional[str]] = mapped_column(String(512))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    api_base_url: Mapped[Optional[str]] = mapped_column(String(1024))
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    timeout: Mapped[int] = mapped_column(Integer, default=120)
    max_chat_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    thinking_token_budget: Mapped[Optional[int]] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[str] = mapped_column("metadata", Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_llm_provider_tenant_slug"),
    )


class UserProfileAccess(Base):
    """Mappa l'accesso di ogni utente ai soli profili selezionati."""

    __tablename__ = "user_profile_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default", server_default="default"
    )
    profile_slug: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "tenant_id",
            "profile_slug",
            name="uq_user_profile_access",
        ),
    )
