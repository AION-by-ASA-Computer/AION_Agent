"""Pydantic schema and validation for agent profile YAML (P2.1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aion.profile_schema")

try:
    from pydantic import BaseModel, Field, field_validator
except ImportError:  # pragma: no cover
    BaseModel = object  # type: ignore[misc, assignment]

    def Field(*a, **k):
        return None

    def field_validator(*a, **k):
        return lambda f: f


class ProfileSchema(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    instructions: str = ""
    skills: List[str] = Field(default_factory=list)
    mcp_servers: List[str] = Field(default_factory=list)
    critical_skills: Optional[List[str]] = None
    native_tool_groups: List[str] = Field(default_factory=list)
    wren_project_path: Optional[str] = None
    max_agent_steps: Optional[int] = None
    agent: Optional[Dict[str, Any]] = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return (v or "").strip()

    @classmethod
    def from_yaml_dict(
        cls, data: Optional[Dict[str, Any]], slug: str
    ) -> "ProfileSchema":
        if not data or not isinstance(data, dict):
            raise ValueError(f"profile {slug}: empty or invalid YAML")
        agent_cfg = data.get("agent") or {}
        max_steps_raw = data.get("max_agent_steps")
        if max_steps_raw is None and isinstance(agent_cfg, dict):
            max_steps_raw = agent_cfg.get("max_steps")
        max_agent_steps: Optional[int] = None
        if max_steps_raw is not None:
            try:
                max_agent_steps = max(1, int(max_steps_raw))
            except (TypeError, ValueError):
                max_agent_steps = None
        cs = data.get("critical_skills")
        if "critical_skills" not in data:
            critical_skills = None
        elif cs is None:
            critical_skills = None
        else:
            critical_skills = list(cs)
        return cls(
            name=str(data.get("name") or slug),
            description=str(data.get("description") or ""),
            instructions=str(data.get("instructions") or ""),
            skills=list(data.get("skills") or []),
            mcp_servers=list(data.get("mcp_servers") or []),
            critical_skills=critical_skills,
            native_tool_groups=list(data.get("native_tool_groups") or []),
            wren_project_path=(data.get("wren_project_path") or None),
            max_agent_steps=max_agent_steps,
            agent=agent_cfg if isinstance(agent_cfg, dict) else None,
        )


@dataclass
class ProfileValidationIssue:
    profile_slug: str
    level: str  # error | warning
    message: str


@dataclass
class ProfileValidationReport:
    issues: List[ProfileValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[ProfileValidationIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> List[ProfileValidationIssue]:
        return [i for i in self.issues if i.level == "warning"]

    def merge(self, other: "ProfileValidationReport") -> None:
        self.issues.extend(other.issues)


def validate_profile_references(
    schema: ProfileSchema,
    slug: str,
    *,
    skill_exists,
    server_exists,
) -> ProfileValidationReport:
    """Check skill and MCP server references (warnings only)."""
    report = ProfileValidationReport()
    for skill in schema.skills or []:
        if skill and not skill_exists(skill):
            report.issues.append(
                ProfileValidationIssue(
                    slug,
                    "warning",
                    f"skill '{skill}' not found in registry",
                )
            )
    for server in schema.mcp_servers or []:
        if server and not server_exists(server):
            report.issues.append(
                ProfileValidationIssue(
                    slug,
                    "warning",
                    f"MCP server '{server}' not found in registry",
                )
            )
    return report


def log_validation_report(report: ProfileValidationReport) -> None:
    for issue in report.warnings:
        logger.warning(
            "Profile validation [%s] %s: %s",
            issue.profile_slug,
            issue.level,
            issue.message,
        )
    for issue in report.errors:
        logger.error(
            "Profile validation [%s] %s: %s",
            issue.profile_slug,
            issue.level,
            issue.message,
        )
