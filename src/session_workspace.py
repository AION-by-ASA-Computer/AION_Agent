"""
Workspace isolato per sessione chat: uploads, derived, workspace (script/dati generati).
Tutti i path sono validati per evitare directory traversal.
"""
from __future__ import annotations

import os
import re
import shutil
import uuid
import mimetypes
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aion.session_workspace")

_SAFE_REL = re.compile(r"^[a-zA-Z0-9._/\-]+$")
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9\-_]{4,128}$")

# Top-level dirs exposed to sandbox list/grep/glob (and typical agent workflows).
SESSION_CONTENT_ROOTS = frozenset({"uploads", "derived", "workspace", "unpacked", ""})

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _running_in_docker() -> bool:
    return Path("/.dockerenv").exists()


def _repo_data_dir() -> Path:
    return (_REPO_ROOT / "data").resolve()


def data_root() -> Path:
    """
    Resolve writable data directory.

    ``AION_DATA_DIR=/app/data`` from Docker templates is rewritten to ``data/``
    when the API runs on the host (path not writable / ``/.dockerenv`` absent).

    Inside sandbox containers, ``AION_DATA_DIR=/session`` with flat mount returns
    ``/session`` directly (session root is the mount point).
    """
    raw = (os.getenv("AION_DATA_DIR") or "data").strip() or "data"
    if _flat_session_mount() and raw == "/session":
        return Path("/session").resolve()

    p = Path(raw)
    if not p.is_absolute():
        return (_REPO_ROOT / p).resolve()

    p = p.resolve()
    fallback = _repo_data_dir()

    docker_template = str(p).startswith("/app/")
    if docker_template and not _running_in_docker():
        logger.warning(
            "AION_DATA_DIR=%s is a Docker path on the host; using %s",
            raw,
            fallback,
        )
        return fallback

    if p.exists():
        if os.access(p, os.W_OK):
            return p
    else:
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except (OSError, PermissionError):
            pass

    if p != fallback:
        logger.warning(
            "AION_DATA_DIR=%s is not writable; using %s",
            raw,
            fallback,
        )
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError):
            pass
        return fallback
    return p


def _flat_session_mount() -> bool:
    if os.environ.get("AION_SANDBOX_FLAT_SESSION_ROOT", "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return True
    return (os.getenv("AION_DATA_DIR") or "").strip() == "/session"


def session_root(session_id: str) -> Path:
    sid = (session_id or "").strip()
    if not _SESSION_ID_RE.match(sid):
        raise ValueError("session_id non valido")
    root = data_root()
    if _flat_session_mount():
        return root.resolve()
    return (root / "sessions" / sid).resolve()


def ensure_session_dirs(session_id: str) -> Path:
    root = session_root(session_id)
    for sub in ("uploads", "derived", "workspace"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _is_under(parent: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def safe_resolve(session_id: str, relative_path: str, *, must_exist: bool = False) -> Path:
    """
    Risolve un path relativo sotto la root sessione (qualsiasi sottopath valido, es. uploads/, workspace/, unpacked/).
    `relative_path` non deve iniziare con / o contenere ..
    """
    rel = (relative_path or "").strip().replace("\\", "/").lstrip("/")
    if ".." in rel or not rel:
        raise ValueError("path non consentito")
    if not _SAFE_REL.match(rel):
        raise ValueError("caratteri path non consentiti")
    root = ensure_session_dirs(session_id)
    full = (root / rel).resolve()
    if not _is_under(root, full):
        raise ValueError("path fuori dalla sessione")
    if must_exist and not full.exists():
        raise FileNotFoundError(relative_path)
    return full


def list_dir(session_id: str, subdir: str = "uploads") -> List[Dict[str, Any]]:
    root = ensure_session_dirs(session_id)
    sub = subdir.strip().replace("\\", "/").strip("/")
    if sub not in SESSION_CONTENT_ROOTS:
        raise ValueError(f"subdir deve essere uno tra: {', '.join(sorted(SESSION_CONTENT_ROOTS))}")
    d = root / sub
    if not d.is_dir():
        return []
    all_names = set(p.name for p in d.iterdir() if p.is_file())
    out: List[Dict[str, Any]] = []
    for p in sorted(d.iterdir()):
        if p.is_file():
            if p.name.startswith("."):
                continue
            if sub == "uploads":
                is_alias = False
                for name in all_names:
                    if name != p.name and name.endswith("_" + p.name) and len(name) == len(p.name) + 11:
                        is_alias = True
                        break
                if is_alias:
                    continue

            rel = f"{subdir}/{p.name}".replace("\\", "/").lstrip("/")
            mime, _ = mimetypes.guess_type(p.name)
            out.append(
                {
                    "name": p.name,
                    "relative_path": rel,
                    "size_bytes": p.stat().st_size,
                    "mime": mime or "application/octet-stream",
                }
            )
    return out


def save_upload(
    session_id: str,
    filename: str,
    data: bytes,
    *,
    max_bytes: Optional[int] = None,
) -> Dict[str, Any]:
    """Salva un file in uploads/ con nome univoco."""
    limit = max_bytes if max_bytes is not None else int(os.getenv("AION_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))
    if len(data) > limit:
        raise ValueError(f"file troppo grande (max {limit} bytes)")
    ensure_session_dirs(session_id)
    base_name = os.path.basename(filename) or "upload"
    safe_name = "".join(c for c in base_name if c.isalnum() or c in "._-")
    if not safe_name or safe_name.startswith("."):
        safe_name = "file_" + uuid.uuid4().hex[:8]
    unique = f"{uuid.uuid4().hex[:10]}_{safe_name}"
    rel = f"uploads/{unique}"
    path = safe_resolve(session_id, rel, must_exist=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    # Also keep a stable alias with original file name so agents can use it directly.
    # If uploaded multiple times with same original name, alias points to latest content.
    alias_rel = f"uploads/{safe_name}"
    alias_path = safe_resolve(session_id, alias_rel, must_exist=False)
    if alias_path != path:
        alias_path.write_bytes(data)
    
    logger.info(
        "File caricato con successo: %s (path: %s, session_id: %s, size: %d bytes)",
        base_name,
        str(path.absolute()),
        session_id,
        len(data),
    )

    mime, _ = mimetypes.guess_type(safe_name)
    return {
        "relative_path": rel,
        "original_relative_path": alias_rel,
        "name": unique,
        "original_name": base_name,
        "size_bytes": len(data),
        "mime": mime or "application/octet-stream",
    }


def sync_parent_uploads_to_child(
    parent_session_id: str,
    child_session_id: str,
) -> Dict[str, Any]:
    """
    Copia i file da ``uploads/`` del parent alla sessione child (MVP isolamento STM + file visibili).
    Limiti: ``AION_SUBAGENT_UPLOAD_SYNC_MAX_TOTAL_MB`` (default 50), ``AION_SUBAGENT_UPLOAD_SYNC_MAX_FILE_MB`` (default 25).
    """
    copied: List[str] = []
    skipped: List[str] = []
    errors: List[str] = []
    parent_sid = (parent_session_id or "").strip()
    child_sid = (child_session_id or "").strip()
    if not _SESSION_ID_RE.match(parent_sid) or not _SESSION_ID_RE.match(child_sid):
        return {
            "ok": False,
            "copied": copied,
            "skipped": skipped,
            "errors": ["invalid session_id"],
            "bytes": 0,
        }
    if parent_sid == child_sid:
        return {"ok": True, "copied": [], "skipped": ["same_session"], "bytes": 0, "errors": []}

    max_total = int(os.getenv("AION_SUBAGENT_UPLOAD_SYNC_MAX_TOTAL_MB", "50")) * 1024 * 1024
    max_file = int(os.getenv("AION_SUBAGENT_UPLOAD_SYNC_MAX_FILE_MB", "25")) * 1024 * 1024

    try:
        parent_root = ensure_session_dirs(parent_sid)
        child_root = ensure_session_dirs(child_sid)
    except ValueError as e:
        return {"ok": False, "copied": [], "skipped": [], "errors": [str(e)], "bytes": 0}

    src_dir = parent_root / "uploads"
    dst_dir = child_root / "uploads"
    dst_dir.mkdir(parents=True, exist_ok=True)
    if not src_dir.is_dir():
        return {"ok": True, "copied": [], "skipped": [], "bytes": 0, "errors": []}

    total = 0
    for p in sorted(src_dir.iterdir()):
        if not p.is_file():
            skipped.append(p.name + " (not a file)")
            continue
        try:
            sz = p.stat().st_size
            if sz > max_file:
                skipped.append(f"{p.name} (file > max_file)")
                continue
            if total + sz > max_total:
                skipped.append(f"{p.name} (budget totale)")
                break
            target = dst_dir / p.name
            shutil.copy2(p, target)
            copied.append(f"uploads/{p.name}")
            total += sz
        except OSError as e:
            errors.append(f"{p.name}: {e}")
            logger.warning("upload sync copy failed %s → child: %s", p, e)

    if errors and not copied:
        ok = False
    else:
        ok = not errors or bool(copied)

    return {
        "ok": ok,
        "copied": copied,
        "skipped": skipped,
        "errors": errors,
        "bytes": total,
    }
