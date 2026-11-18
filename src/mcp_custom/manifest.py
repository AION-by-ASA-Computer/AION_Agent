"""The ``aion-mcp.yaml`` manifest of a customer-built MCP server (format ``aion_mcp: 1``).

AION ships the format (template + JSON Schema, see ``docs/mcp/custom-mcp-servers.md``);
each server fills in its own values. The manifest is the single source of truth for
the server identity, its credential mode/schema and its non-secret configuration:
the boot sync and admin-ui read them from here, never from heuristics.

Rules kept on purpose simple and aligned with the rest of AION:

- one credential mode per server (``none`` / ``org_shared`` / ``per_user``), as for
  every other MCP integration;
- strict schema: unknown fields are rejected with an explicit error, never ignored;
- v0 accepts only ``runtime: python`` (``node`` and ``binary`` are planned for v1).

Used by ``package`` (parse/validate uploads), ``install`` (registry entry) and the
admin API (manifest form for single ``.py`` uploads).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .paths import slug_format_error

MANIFEST_FILENAMES = ("aion-mcp.yaml", "aion-mcp.yml")
MANIFEST_FORMAT_VERSION = 1

CredentialMode = Literal["none", "org_shared", "per_user"]

# Runtimes known to the format. Only "python" is installable in v0; the others are
# recognised so the error message can say they are planned rather than "unknown".
SUPPORTED_RUNTIMES = ("python",)
PLANNED_RUNTIMES = ("node", "binary")

_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_ENTRYPOINT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*\.py$")

# Variables AION sets itself or that change how the interpreter loads code: a
# manifest may not declare them, otherwise a package could hijack module loading
# (PYTHONPATH, LD_PRELOAD) or impersonate AION context (AION_CURRENT_USER_ID).
_RESERVED_ENV_KEYS = frozenset(
    {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TEMP", "TMP", "LANG", "TERM"}
)
_RESERVED_ENV_PREFIXES = (
    "AION_",
    "PYTHON",
    "LD_",
    "DYLD_",
    "XDG_",
    "UV_",
    "PIP_",
    "NPM_CONFIG_",
    "FASTMCP_",
    "LC_",
)


class ManifestError(ValueError):
    """Invalid manifest: ``errors`` holds one human-readable message per problem."""

    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def env_key_error(key: str) -> Optional[str]:
    """Reason why ``key`` cannot be an env/credential variable name, or None.

    Single rule for every place a custom server's variable names come from: the
    manifest (upload), admin edits in the MCP Hub (``PUT /admin/mcp/{name}``) and
    the spawn policy (``runtime``), which drops reserved names from the registry.
    """
    if not _ENV_KEY_RE.match(key):
        return f"'{key}' must be UPPER_SNAKE_CASE (letters, digits, underscores)"
    if key in _RESERVED_ENV_KEYS or key.startswith(_RESERVED_ENV_PREFIXES):
        return f"'{key}' is reserved by AION and cannot be declared"
    return None


class CredentialField(BaseModel):
    """One credential the server needs; its value is entered in AION, never in the file."""

    model_config = ConfigDict(extra="forbid")

    # Name of the environment variable the server reads (os.environ["KEY"]).
    key: str
    # Label shown in the admin form (org_shared) or in "My integrations" (per_user).
    label: str = Field(min_length=1, max_length=120)
    # True: masked in forms and stored encrypted. False: plain value (e.g. a company code).
    secret: bool = True
    # True: the integration stays "to configure" until the value is provided.
    required: bool = True
    description: Optional[str] = Field(default=None, max_length=500)

    @field_validator("key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        err = env_key_error(v)
        if err:
            raise ValueError(err)
        return v


class Credentials(BaseModel):
    """Which secrets the server needs and who provides them (one mode per server)."""

    model_config = ConfigDict(extra="forbid")

    mode: CredentialMode = "none"
    fields: List[CredentialField] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_mode_fields(self) -> "Credentials":
        if self.mode == "none" and self.fields:
            raise ValueError("credentials.fields must be empty when mode is 'none'")
        if self.mode != "none" and not self.fields:
            raise ValueError(f"credentials.fields must list at least one field for mode '{self.mode}'")
        keys = [f.key for f in self.fields]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            raise ValueError(f"duplicate credential keys: {', '.join(dupes)}")
        return self


class Manifest(BaseModel):
    """Parsed ``aion-mcp.yaml``. See the module docstring for the rules."""

    model_config = ConfigDict(extra="forbid")

    aion_mcp: int
    slug: str
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    version: str
    runtime: str = "python"
    entrypoint: str = "server.py"
    credentials: Credentials = Field(default_factory=Credentials)
    # Non-secret configuration, written in clear in the registry and editable by the
    # admin afterwards. Secrets belong in ``credentials``.
    env: Dict[str, str] = Field(default_factory=dict)
    # Network allowlist: the only destinations the server may reach (host names,
    # IPs or subnets, with optional ports; format in ``egress``). Empty or absent:
    # no network at all. The admin can change it from the MCP Hub.
    network: List[str] = Field(default_factory=list)

    @field_validator("network", mode="before")
    @classmethod
    def _check_network(cls, v: Any) -> List[str]:
        """Validate and normalize the allowlist (canonical strings, no duplicates)."""
        from .egress import AllowlistError, normalize_allowlist

        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("network must be a list of addresses, e.g. ['crm.azienda.local:443']")
        try:
            return normalize_allowlist(str(item) for item in v)
        except AllowlistError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("aion_mcp")
    @classmethod
    def _check_format(cls, v: int) -> int:
        if v != MANIFEST_FORMAT_VERSION:
            raise ValueError(f"unsupported manifest format {v}: this AION reads aion_mcp: {MANIFEST_FORMAT_VERSION}")
        return v

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, v: str) -> str:
        err = slug_format_error(v)
        if err:
            raise ValueError(err)
        return v

    @field_validator("version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if not _VERSION_RE.match(v):
            raise ValueError("version must look like 1.0.0 (MAJOR.MINOR.PATCH)")
        return v

    @field_validator("runtime")
    @classmethod
    def _check_runtime(cls, v: str) -> str:
        if v in SUPPORTED_RUNTIMES:
            return v
        if v in PLANNED_RUNTIMES:
            raise ValueError(f"runtime '{v}' is not available yet (planned for AION custom MCP v1); use 'python'")
        raise ValueError(f"unknown runtime '{v}'; use 'python'")

    @field_validator("entrypoint")
    @classmethod
    def _check_entrypoint(cls, v: str) -> str:
        norm = v.replace("\\", "/")
        while norm.startswith("./"):
            norm = norm[2:]
        if not _ENTRYPOINT_RE.match(norm) or ".." in norm.split("/"):
            raise ValueError("entrypoint must be a relative path to a .py file inside the package")
        return norm

    @field_validator("env")
    @classmethod
    def _check_env(cls, v: Dict[str, str]) -> Dict[str, str]:
        errors: List[str] = []
        for key, value in v.items():
            err = env_key_error(key)
            if err:
                errors.append(f"env {err}")
            # Placeholders would be expanded from the backend environment at spawn
            # time: a manifest must never be able to pull AION's own secrets.
            if "${" in str(value):
                errors.append(f"env '{key}': placeholders like ${{VAR}} are not allowed; declare secrets in credentials")
            if len(str(value)) > 2000:
                errors.append(f"env '{key}': value too long (max 2000 characters)")
        if errors:
            raise ValueError("; ".join(errors))
        return {k: str(val) for k, val in v.items()}

    @model_validator(mode="after")
    def _check_overlap(self) -> "Manifest":
        overlap = sorted(set(self.env) & {f.key for f in self.credentials.fields})
        if overlap:
            raise ValueError(f"keys declared both in env and credentials: {', '.join(overlap)}")
        return self

    # ── conversions used by install / admin API ──

    def credential_schema(self) -> List[Dict[str, Any]]:
        """Credential fields in the format of ``McpServerConfig.credential_schema``.

        Same shape the catalog and the Hub already use (key/label/type/required/
        description), plus ``is_secret`` read by the org_shared secret handling.
        """
        return [
            {
                "key": f.key,
                "label": f.label,
                "type": "password" if f.secret else "text",
                "required": f.required,
                "description": f.description,
                "is_secret": f.secret,
            }
            for f in self.credentials.fields
        ]

    def secret_keys(self) -> List[str]:
        """Credential keys that must be stored encrypted."""
        return [f.key for f in self.credentials.fields if f.secret]

    def to_yaml(self) -> str:
        """Serialise as ``aion-mcp.yaml`` (used when AION generates the manifest)."""
        data = self.model_dump(exclude_none=True)
        header = (
            "# aion-mcp.yaml - manifest of an AION custom MCP server.\n"
            "# Generated by AION from the upload form: keep it with your code so the\n"
            "# next upload does not need the form again.\n"
            "# Reference: docs/mcp/custom-mcp-servers.md\n"
        )
        return header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _format_validation_error(exc: ValidationError) -> List[str]:
    """Flatten pydantic errors into ``field.path: message`` strings for the admin UI."""
    out: List[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "__root__")
        msg = str(err.get("msg") or "invalid value")
        msg = msg.removeprefix("Value error, ")
        if err.get("type") == "extra_forbidden":
            msg = "unknown field (not part of the aion-mcp.yaml format)"
        out.append(f"{loc}: {msg}" if loc else msg)
    return out


def parse_manifest_data(data: Any) -> Manifest:
    """Validate an already-decoded manifest (dict). Raises ``ManifestError``."""
    if not isinstance(data, dict):
        raise ManifestError(["the manifest must be a YAML mapping (key: value)"])
    try:
        return Manifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestError(_format_validation_error(exc)) from exc


def parse_manifest_text(text: str) -> Manifest:
    """Parse and validate the text of an ``aion-mcp.yaml``. Raises ``ManifestError``."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError([f"invalid YAML: {exc}"]) from exc
    return parse_manifest_data(data)


def manifest_json_schema() -> Dict[str, Any]:
    """JSON Schema of the manifest, for IDE autocompletion (published with the template)."""
    return Manifest.model_json_schema()
