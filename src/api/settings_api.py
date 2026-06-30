import os
import asyncio
import logging
from pathlib import Path
from typing import Dict, Set
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("aion.settings_api")

router = APIRouter(prefix="/settings", tags=["settings"])


def _get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _get_env_path() -> Path:
    if os.path.exists("/.dockerenv"):
        data_dir = os.environ.get("AION_DATA_DIR", "/app/data")
        return Path(data_dir) / "runtime.env"
    return _get_repo_root() / ".env"


def _parse_env() -> Dict[str, str]:
    path = _get_env_path()
    out = {}

    # Initialize from current system process environment (only AION_* keys)
    for k, v in os.environ.items():
        if k.startswith("AION_"):
            out[k] = v

    if not path.is_file():
        return out

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            key = k.strip()
            val = v.strip().strip('"').strip("'")
            out[key] = val
    except Exception as e:
        logger.error(f"Failed to parse env file {path}: {e}")

    return out


def _is_sensitive_env_key(key: str) -> bool:
    if key in ("AION_LLM_API_KEY", "AION_EMBEDDINGS_API_KEY"):
        return False
    ku = key.upper()
    needles = (
        "SECRET",
        "PASSWORD",
        "_API_KEY",
        "AUTH_TOKEN",
        "INTERNAL_SECRET",
        "CHAT_AUTH",
        "OCR_API_KEY",
        "BRAVE_SEARCH_API",
        "TAVILY_API",
    )
    return any(n in ku for n in needles)


def _is_masked_placeholder(val: str) -> bool:
    v = (val or "").strip()
    if v == "***":
        return True
    if len(v) >= 4 and set(v) <= {"*", "•", "…"}:
        return True
    return False


def _mask_settings_for_get(raw: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in raw.items():
        if _is_sensitive_env_key(k) and v:
            out[k] = "***"
        else:
            out[k] = v
    return out


def _filter_settings_post(updates: Dict[str, str]) -> Dict[str, str]:
    """Non sovrascrivere segreti se il client re-invia il placeholder da GET mascherato."""
    out: Dict[str, str] = {}
    for k, v in updates.items():
        if _is_sensitive_env_key(k) and _is_masked_placeholder(str(v)):
            continue
        out[k] = v if v is not None else ""
    return out


def _write_env(updates: Dict[str, str]):
    path = _get_env_path()

    # Ensure the parent directory (e.g. /app/data) exists
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = []

    if not path.is_file():
        for k, v in updates.items():
            lines.append(f"{k}={v}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    current_content = path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    seen_keys: Set[str] = set()

    for line in current_content:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, _ = stripped.partition("=")
            key = k.strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                seen_keys.add(key)
                continue
        new_lines.append(line)

    for k, v in updates.items():
        if k not in seen_keys:
            new_lines.append(f"{k}={v}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _resolve_provider_type(env_dict: Dict[str, str]) -> str:
    adapter = (env_dict.get("AION_LLM_ADAPTER") or "").strip().lower()
    model = (env_dict.get("AION_MODEL") or "").strip().lower()

    if "anthropic" in adapter or "anthropic" in model or "claude" in model:
        return "anthropic"
    elif "google" in adapter or "gemini" in adapter or "gemini" in model:
        return "google"
    else:
        return "openai"


class SettingsUpdate(BaseModel):
    settings: Dict[str, str]


@router.get("")
async def get_settings():
    """Retrieve current .env settings (segreti mascherati)."""
    env_dict = _parse_env()
    provider_type = _resolve_provider_type(env_dict)
    return {
        "settings": _mask_settings_for_get(env_dict),
        "provider_type": provider_type,
    }


async def _deferred_exit():
    await asyncio.sleep(1.0)
    logger.info("Exiting process to trigger container restart...")
    os._exit(0)


@router.post("")
async def update_settings(update: SettingsUpdate):
    """Update .env settings."""
    try:
        merged = _filter_settings_post(dict(update.settings))

        # Validation: If provider is anthropic, AION_CHAT_MAX_TOKENS must be > AION_THINKING_TOKEN_BUDGET
        adapter = merged.get("AION_LLM_ADAPTER") or ""
        model = merged.get("AION_MODEL") or ""
        is_anthropic = (
            "anthropic" in adapter.lower()
            or "anthropic" in model.lower()
            or "claude" in model.lower()
        )

        if is_anthropic:
            max_tokens_str = merged.get("AION_CHAT_MAX_TOKENS")
            thinking_str = merged.get("AION_THINKING_TOKEN_BUDGET")
            if max_tokens_str and thinking_str:
                try:
                    max_tokens = int(max_tokens_str)
                    thinking = int(thinking_str)
                    if max_tokens <= thinking:
                        raise HTTPException(
                            status_code=400,
                            detail="For Anthropic provider, Max Chat Tokens (AION_CHAT_MAX_TOKENS) must be greater than Thinking Token Budget (AION_THINKING_TOKEN_BUDGET).",
                        )
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail="Max Chat Tokens and Thinking Token Budget must be valid integers.",
                    )

        # Validation: AION_LLM_TIMEOUT must be a valid integer
        timeout_str = merged.get("AION_LLM_TIMEOUT")
        if timeout_str:
            try:
                int(timeout_str)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="LLM Timeout (AION_LLM_TIMEOUT) must be a valid integer.",
                )

        _write_env(merged)

        restarting = False
        if os.path.exists("/.dockerenv"):
            restarting = True
            logger.info("Docker environment detected. Scheduling container restart...")
            asyncio.create_task(_deferred_exit())

        return {
            "status": "success",
            "message": "Settings updated. Restarting API container..."
            if restarting
            else "Settings updated. Some changes may require a restart.",
            "restarting": restarting,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class FSPolicyResponse(BaseModel):
    path: str
    enabled: bool
    yaml_content: str
    dev_template: str
    example_template: str


class FSPolicyUpdate(BaseModel):
    yaml_content: str
    enabled: bool


@router.get("/fs-policy", response_model=FSPolicyResponse)
async def get_fs_policy():
    """Get the current filesystem policy and templates."""
    env_dict = _parse_env()
    path_str = (env_dict.get("AION_FS_POLICY_PATH") or "").strip()
    enabled = bool(path_str)

    if not path_str:
        path_str = "config/fs_policy.yaml"

    repo_root = _get_repo_root()
    policy_path = repo_root / path_str

    yaml_content = ""
    if policy_path.is_file():
        try:
            yaml_content = policy_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read policy file {policy_path}: {e}")

    dev_template_path = repo_root / "config_std" / "fs_policy.dev.yaml"
    example_template_path = repo_root / "config_std" / "fs_policy.example.yaml"

    dev_template = ""
    if dev_template_path.is_file():
        dev_template = dev_template_path.read_text(encoding="utf-8")

    example_template = ""
    if example_template_path.is_file():
        example_template = example_template_path.read_text(encoding="utf-8")

    if not yaml_content:
        yaml_content = dev_template

    return FSPolicyResponse(
        path=path_str,
        enabled=enabled,
        yaml_content=yaml_content,
        dev_template=dev_template,
        example_template=example_template,
    )


@router.post("/fs-policy")
async def update_fs_policy(body: FSPolicyUpdate):
    """Update the filesystem policy YAML and toggle its enablement in .env."""
    try:
        env_dict = _parse_env()
        path_str = (env_dict.get("AION_FS_POLICY_PATH") or "").strip()
        if not path_str:
            path_str = "config/fs_policy.yaml"

        repo_root = _get_repo_root()
        policy_path = repo_root / path_str

        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(body.yaml_content, encoding="utf-8")

        updates = {}
        if body.enabled:
            updates["AION_FS_POLICY_PATH"] = path_str
        else:
            updates["AION_FS_POLICY_PATH"] = ""

        _write_env(updates)

        restarting = False
        if os.path.exists("/.dockerenv"):
            restarting = True
            logger.info("Docker environment detected. Scheduling container restart...")
            asyncio.create_task(_deferred_exit())

        return {
            "status": "success",
            "message": "Filesystem policy updated. Restarting API container..."
            if restarting
            else "Filesystem policy updated. Some changes may require a restart.",
            "restarting": restarting,
        }
    except Exception as e:
        logger.error(f"Failed to update filesystem policy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

