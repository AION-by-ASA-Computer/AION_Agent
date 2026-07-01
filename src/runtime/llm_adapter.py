"""Resolve LLM endpoint and model from environment (no hardcoded private IPs)."""

from __future__ import annotations

import logging
import os
from typing import Tuple

logger = logging.getLogger("aion.llm_generator")


def resolve_llm_credentials() -> Tuple[str, str, str]:
    """
    Returns (api_url, model_name, api_key).
    Resolves default provider from SQLite DB if available, falling back to environment variables.
    """
    db_url = os.getenv("AION_DB_URL", "sqlite+aiosqlite:///data/aion.db")
    if "sqlite" in db_url:
        db_path = db_url.split("///")[-1]
        import sqlite3
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[2]
        p = Path(db_path)
        if not p.is_absolute():
            p = repo_root / p
        
        if p.exists():
            try:
                conn = sqlite3.connect(str(p))
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT api_base_url, provider, model_name, api_key_encrypted FROM llm_providers "
                    "WHERE tenant_id = 'default' AND enabled = 1 AND is_default = 1 LIMIT 1"
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        "SELECT api_base_url, provider, model_name, api_key_encrypted FROM llm_providers "
                        "WHERE tenant_id = 'default' AND enabled = 1 LIMIT 1"
                    )
                    row = cursor.fetchone()
                
                if row:
                    api_base_url, provider, model_name, api_key_encrypted = row
                    cursor.close()
                    conn.close()
                    
                    # Decrypt key if present
                    api_key = "placeholder-token"
                    if api_key_encrypted:
                        try:
                            from src.runtime.credential_store import decrypt_value
                            api_key = decrypt_value(api_key_encrypted)
                        except Exception:
                            pass
                    else:
                        api_key = os.getenv("AION_LLM_API_KEY", "placeholder-token")
                    
                    if api_base_url:
                        full_model = f"{provider}/{model_name}" if "/" not in model_name else model_name
                        url = api_base_url.strip().rstrip("/")
                        if not url.startswith(("http://", "https://")):
                            url = "http://" + url
                        return url, full_model, api_key
            except Exception as e:
                logger.warning("Failed to query default LLM provider from SQLite: %s", e)

        else:
            raise ValueError("No LLM provider configured. Please configure one in the Admin UI.")




def resolve_llm_endpoint() -> Tuple[str, str]:
    """
    Returns (api_url, model_name).
    """
    url, model, _ = resolve_llm_credentials()
    return url, model


def resolve_llm_adapter() -> str:
    return (os.getenv("AION_LLM_ADAPTER") or "vllm_qwen").strip()


def resolve_llm_timeout(default: int = 120) -> int:
    try:
        return int(os.getenv("AION_LLM_TIMEOUT", str(default)))
    except ValueError:
        return default
