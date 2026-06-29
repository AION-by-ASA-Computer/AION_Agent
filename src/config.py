import yaml
import os
from pathlib import Path
from typing import Any, Optional


def resolve_env_placeholders(
    obj: Any,
    *,
    user_id: str = "",
    tenant_id: str = "default",
    server_slug: str = "",
) -> Any:
    """
    Sostituisce stringhe `${VAR}` con os.environ (ricorsivo).
    Placeholder `${AION_USER_*}` per credenziali per-utente non sono risolti qui:
    vengono applicati in async da ``resolve_mcp_env_for_user`` al spawn MCP.
    """
    if isinstance(obj, dict):
        return {
            k: resolve_env_placeholders(
                v, user_id=user_id, tenant_id=tenant_id, server_slug=server_slug
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [
            resolve_env_placeholders(
                i, user_id=user_id, tenant_id=tenant_id, server_slug=server_slug
            )
            for i in obj
        ]
    if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
        env_var = obj[2:-1]
        if env_var.startswith("AION_USER_"):
            return obj
        _ = user_id, tenant_id, server_slug  # API estesa per compat futura
        return os.environ.get(env_var, obj)
    return obj


class Config:
    def __init__(self, config_path: str = "config/default.yaml"):
        self.base_path = Path(__file__).parent.parent
        self.config_path = self.base_path / config_path
        self._data = {}
        self.load()

    def load(self):
        try:
            from dotenv import load_dotenv

            load_dotenv(self.base_path / ".env")
            load_dotenv(self.base_path / ".env.local", override=False)

            data_dir = os.environ.get("AION_DATA_DIR", "data")
            data_path = Path(data_dir)
            if not data_path.is_absolute():
                data_path = self.base_path / data_path
            runtime_env = data_path / "runtime.env"
            if runtime_env.is_file():
                load_dotenv(runtime_env, override=True)
        except ImportError:
            pass
        if not self.config_path.exists():
            # Minimal fallback if file doesn't exist yet
            self._data = {}
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
            self._data = resolve_env_placeholders(raw)

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        val = self._data
        try:
            for k in keys:
                val = val[k]
            return val
        except (KeyError, TypeError):
            return default


# Singleton instance
config = Config()
