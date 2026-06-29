"""Catalog-driven runtime env aliases (no per-connector code in mcp_manager)."""

from src.mcp_connector_catalog import (
    apply_runtime_env_aliases,
    resolve_connector_row_for_mcp_server,
)
from src.mcp_manager import _merge_mcp_subprocess_env


def test_merge_mcp_subprocess_env_skips_empty_strings():
    env = {"clickupApiKey": "from-host-env"}
    _merge_mcp_subprocess_env(
        env,
        {"clickupApiKey": "   ", "clickupTeamId": "9012"},
    )
    assert env["clickupApiKey"] == "from-host-env"
    assert env["clickupTeamId"] == "9012"


def test_resolve_prefers_aion_connector_id():
    catalog = {
        "connectors": [
            {"id": "clickup", "runtime_env_aliases": {"X": ["Y"]}},
            {"id": "other", "runtime_env_aliases": {"P": ["Q"]}},
        ]
    }
    cfg = {"aion_connector_id": "clickup"}
    row = resolve_connector_row_for_mcp_server("anything", cfg, catalog)
    assert row and row["id"] == "clickup"


def test_apply_aliases_dict_form_in_catalog():
    catalog = {
        "connectors": [
            {
                "id": "clickup",
                "mcp_name_hints": ["clickup"],
                "runtime_env_aliases": {
                    "CLICKUP_API_KEY": [
                        "clickupApiKey",
                        "CLICKUP_API_TOKEN",
                        "CLICKUP_PERSONAL_TOKEN",
                    ],
                    "CLICKUP_TEAM_ID": ["clickupTeamId"],
                },
            }
        ]
    }
    env = {"CLICKUP_API_TOKEN": "tok", "CLICKUP_TEAM_ID": "t1"}
    apply_runtime_env_aliases(env, "my_clickup", {}, catalog=catalog)
    assert env["CLICKUP_API_KEY"] == "tok"
    assert env["CLICKUP_TEAM_ID"] == "t1"


def test_apply_clickup_aliases_from_registry_style_keys():
    """Registry YAML tipico: clickupApiKey/clickupTeamId → CLICKUP_* (pacchetto consigliato @hauptsache.net/clickup-mcp)."""
    catalog = {
        "connectors": [
            {
                "id": "clickup",
                "mcp_name_hints": ["clickup"],
                "runtime_env_aliases": {
                    "CLICKUP_API_KEY": [
                        "clickupApiKey",
                        "CLICKUP_API_TOKEN",
                        "CLICKUP_PERSONAL_TOKEN",
                    ],
                    "CLICKUP_TEAM_ID": ["clickupTeamId"],
                },
            }
        ]
    }
    env = {"clickupApiKey": "pk_x", "clickupTeamId": "9012"}
    apply_runtime_env_aliases(env, "clickup-mcp-server", {}, catalog=catalog)
    assert env["CLICKUP_API_KEY"] == "pk_x"
    assert env["CLICKUP_TEAM_ID"] == "9012"


def test_apply_aliases_list_form_in_catalog():
    catalog = {
        "connectors": [
            {
                "id": "demo",
                "mcp_name_hints": ["demo"],
                "runtime_env_aliases": [
                    {"env_key": "NEED", "from_env_keys": ["ALT1", "ALT2"]},
                ],
            }
        ]
    }
    env = {"ALT2": "v2"}
    apply_runtime_env_aliases(env, "demo-mcp", {}, catalog=catalog)
    assert env["NEED"] == "v2"


def test_apply_does_not_override_existing_target():
    catalog = {
        "connectors": [
            {
                "id": "clickup",
                "mcp_name_hints": ["clickup"],
                "runtime_env_aliases": {"CLICKUP_API_KEY": ["CLICKUP_API_TOKEN"]},
            }
        ]
    }
    env = {"CLICKUP_API_KEY": "keep", "CLICKUP_API_TOKEN": "drop"}
    apply_runtime_env_aliases(env, "clickup", {}, catalog=catalog)
    assert env["CLICKUP_API_KEY"] == "keep"


def test_apply_no_row_noop():
    env = {"FOO": "1"}
    apply_runtime_env_aliases(env, "unknown_server_xyz", {}, catalog={"connectors": []})
    assert env == {"FOO": "1"}
