"""Environment flags and limits for customer-built MCP servers.

Read on every call (not cached) so tests and admins changing ``.env`` +
restarting see the new values. Who uses it: the admin API (upload limits, feature
gate), the package validator and the spawn policy in ``runtime``.
"""

from __future__ import annotations

import os


def _truthy(name: str, default: str = "0") -> bool:
    """True when the env var holds an affirmative value (1/true/yes/on)."""
    return (os.environ.get(name, default) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _int(name: str, default: int, *, minimum: int = 1) -> int:
    """Positive integer from the environment, falling back on bad values."""
    try:
        return max(minimum, int((os.environ.get(name) or "").strip() or default))
    except ValueError:
        return default


def upload_enabled() -> bool:
    """Upload and management from admin-ui.

    Off by default. Editable from admin-ui (Settings -> MCPs, stored as a runtime
    override by ``src/api/settings_api.py``) or in ``.env``; applied without a
    restart because it is read on every call.
    """
    return _truthy("AION_CUSTOM_MCP_ENABLED")


def force_disabled() -> bool:
    """Kill switch: no custom server process is started while this is set."""
    return _truthy("AION_CUSTOM_MCP_FORCE_DISABLE")


def allow_unsandboxed() -> bool:
    """Development escape hatch: run custom servers without container isolation.

    ``.env`` only: the settings API refuses to change it from the web panel.

    Custom servers must run in their own container (see the plan, section 3).
    Until the container runner ships, or on machines without a container runtime,
    a custom server only starts when this flag is explicitly set. Never enable it
    in production: the process would share the backend container.
    """
    return _truthy("AION_CUSTOM_MCP_ALLOW_UNSANDBOXED")


def max_upload_bytes() -> int:
    """Maximum size of the uploaded file (``AION_CUSTOM_MCP_MAX_UPLOAD_MB``, default 20)."""
    return _int("AION_CUSTOM_MCP_MAX_UPLOAD_MB", 20) * 1024 * 1024


def max_unpacked_bytes() -> int:
    """Maximum total size once a zip is extracted (zip-bomb guard): 5x the upload limit."""
    return max_upload_bytes() * 5


def max_files() -> int:
    """Maximum number of files in a zip (``AION_CUSTOM_MCP_MAX_FILES``, default 500)."""
    return _int("AION_CUSTOM_MCP_MAX_FILES", 500)


def keep_versions() -> int:
    """Previous versions kept under ``.versions/<slug>/`` (``AION_CUSTOM_MCP_KEEP_VERSIONS``, default 3)."""
    return _int("AION_CUSTOM_MCP_KEEP_VERSIONS", 3, minimum=0)


def staging_ttl_seconds() -> int:
    """Uploads never activated are removed after this delay (24 hours)."""
    return 24 * 3600


def build_timeout_seconds() -> int:
    """Maximum duration of the dependency build container (``AION_CUSTOM_MCP_BUILD_TIMEOUT``, default 300)."""
    return _int("AION_CUSTOM_MCP_BUILD_TIMEOUT", 300)


def probe_timeout_seconds() -> int:
    """Maximum time for the verification probe (start + list_tools) (``AION_CUSTOM_MCP_PROBE_TIMEOUT``, default 90)."""
    return _int("AION_CUSTOM_MCP_PROBE_TIMEOUT", 90)


def allow_source_builds() -> bool:
    """Allow packages without a wheel (source builds run their setup.py).

    Off by default: installing wheels never executes code of the packages, so the
    only moment the build container has network access runs pip alone. Even when
    enabled, the source build stays inside the build jail.
    """
    return _truthy("AION_CUSTOM_MCP_ALLOW_SOURCE_BUILDS")
