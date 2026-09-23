"""
Admin API endpoints for Agent Smoke Tests & Diagnostics Suite.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger("aion.api.diagnostics")
SAFE_REL_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SMOKE_TESTS_DIR = REPO_ROOT / "evals" / "agent_smoke_tests"
CONFIG_FILE = SMOKE_TESTS_DIR / "test_config.json"
OUTPUTS_DIR = SMOKE_TESTS_DIR / "outputs"


class RunTestsRequest(BaseModel):
    test_id: Optional[str] = None
    profile: Optional[str] = None


SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
SAFE_REPORT_NAME_RE = re.compile(r"^report_[a-zA-Z0-9_-]+\.md$")


def _is_safe_path(target: Path | str, allowed_bases: List[Path | str]) -> bool:
    """Verifies that a resolved target path resides strictly within one of the allowed base directories."""
    try:
        t_res = Path(target).resolve()
        for base in allowed_bases:
            b_res = Path(base).resolve()
            if t_res.is_relative_to(b_res):
                return True
    except Exception:
        return False
    return False


@router.get("/config")
async def get_test_config() -> List[Dict[str, Any]]:
    """Returns the list of test cases configured for smoke testing."""
    if not CONFIG_FILE.exists():
        raise HTTPException(status_code=404, detail="test_config.json not found")
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Failed to read test config: {ex}")


@router.get("/reports")
async def list_reports() -> List[Dict[str, Any]]:
    """Lists all generated smoke test markdown reports."""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    reports = []
    outputs_dir_resolved = OUTPUTS_DIR.resolve()
    for p in sorted(
        OUTPUTS_DIR.glob("report_*.md"), key=lambda x: x.stat().st_mtime, reverse=True
    ):
        try:
            p_resolved = p.resolve(strict=True)
            if not p_resolved.is_relative_to(outputs_dir_resolved):
                continue
            st = p_resolved.stat()
            reports.append(
                {
                    "filename": p_resolved.name,
                    "size_bytes": st.st_size,
                    "modified_at": datetime.fromtimestamp(
                        st.st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
            )
        except Exception:
            continue
    return reports


@router.get("/reports/{filename}")
async def get_report_content(filename: str) -> Dict[str, Any]:
    """Returns the content of a specific test report with strict path and filename validation."""
    if not SAFE_REPORT_NAME_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid report filename format")

    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid report filename format")

    outputs_dir_resolved = OUTPUTS_DIR.resolve()
    target = (outputs_dir_resolved / safe_name).resolve()

    if not target.is_relative_to(outputs_dir_resolved):
        raise HTTPException(status_code=400, detail="Path traversal detected")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Report file not found")

    try:
        content = target.read_text(encoding="utf-8")
        st = target.stat()
        return {
            "filename": safe_name,
            "content": content,
            "size_bytes": st.st_size,
            "modified_at": datetime.fromtimestamp(
                st.st_mtime, tz=timezone.utc
            ).isoformat(),
        }
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {ex}")


def _resolve_file_within(base_dir: Path | str, candidate: Path | str) -> Optional[Path]:
    """Resolve candidate and ensure it stays within base_dir and is an existing file."""
    try:
        base_resolved = Path(base_dir).resolve(strict=True)
        candidate_path = Path(candidate)

        # Never resolve attacker-controlled absolute paths directly.
        # Candidate must be interpreted as a path relative to the trusted base
        if candidate_path.is_absolute():
            return None

        combined = (base_resolved / candidate_path).resolve(strict=True)
        if combined.is_relative_to(base_resolved) and combined.is_file():
            return combined

    except Exception:
        return None
    return None


def _finalize_allowed_file(candidate: Path, allowed_bases: List[Path]) -> Optional[Path]:
    """Return a strictly resolved file path only if it is within one of the allowed bases."""
    try:
        resolved = candidate.resolve(strict=True)
    except Exception:
        return None

    if not resolved.is_file():
        return None

    for base in allowed_bases:
        try:
            if resolved.is_relative_to(base):
                return resolved
        except Exception:
            continue
    return None


def resolve_diagnostic_file(
    raw_path: str, session_id: Optional[str] = None
) -> Optional[Path]:
    """
    Risolve in modo sicuro file/immagini generati durante le sessioni di test fumo.
    Supporta URI file://, path assoluti/relativi sessione (data/sessions/.../workspace/...),
    path workspace diretti o semplici nomi file cercandoli nell'ultima sessione smoke.
    Garantisce che qualsiasi percorso risolto ricada rigidamente all'interno di data/sessions o evals/.../outputs.
    """
    from src.session_workspace import data_root

    if not raw_path or "\x00" in raw_path:
        return None

    clean = raw_path.strip().replace("\\", "/")
    clean = re.sub(r"^file:/*(app/)?", "", clean)
    clean = clean.lstrip("/")

    if (
        not clean
        or not SAFE_REL_PATH_RE.fullmatch(clean)
        or ".." in clean
        or clean.startswith(("/", "\\"))
        or "//" in clean
    ):
        return None

    d_root = data_root().resolve()
    sessions_dir = (d_root / "sessions").resolve()
    outputs_dir = OUTPUTS_DIR.resolve()
    allowed_bases = [sessions_dir, outputs_dir]

    def _check(candidate: Path) -> Optional[Path]:
        for base in allowed_bases:
            res = _resolve_file_within(base, candidate)
            if res is not None:
                return _finalize_allowed_file(res, allowed_bases)
        return None

    # 1. Path strutturato con prefisso sessions/ o data/sessions/
    if "sessions/" in clean:
        rel = clean.split("sessions/", 1)[1]
        found = _check(sessions_dir / rel)
        if found:
            return found

    # 2. Se viene specificato un session_id (validato con regex rigorosa)
    if session_id:
        if not SAFE_ID_RE.fullmatch(session_id):
            return None
        for cand in [
            sessions_dir / session_id / clean,
            sessions_dir / session_id / "workspace" / clean,
            sessions_dir / session_id / "derived" / clean,
        ]:
            found = _check(cand)
            if found:
                return found

    # 3. Controlla in outputs/
    if "outputs/" in clean:
        rel = clean.split("outputs/", 1)[1]
        found = _check(outputs_dir / rel)
        if found:
            return found
    if outputs_dir.exists():
        found = _check(outputs_dir / clean)
        if found:
            return found

    # 4. Cerca nelle directory sessioni smoke recenti solo per nome file singolo sicuro
    filename = Path(clean).name
    if (
        filename
        and SAFE_ID_RE.fullmatch(filename.replace(".", "_"))
        and sessions_dir.exists()
    ):
        for s_dir in sorted(
            sessions_dir.glob("smoke_*"), key=lambda x: x.stat().st_mtime, reverse=True
        ):
            if not _is_safe_path(s_dir, [sessions_dir]):
                continue
            for candidate in [
                s_dir / filename,
                s_dir / "workspace" / filename,
                s_dir / "derived" / filename,
                s_dir / "uploads" / filename,
            ]:
                found = _check(candidate)
                if found:
                    return found

    return None


@router.get("/file")
async def get_diagnostic_file(
    path: str = Query(
        ..., description="Path relativo al workspace di sessione o URI del file"
    ),
    session_id: Optional[str] = Query(None, description="ID sessione opzionale"),
    download: bool = Query(
        False, description="Forza header attachment per download diretto"
    ),
):
    """
    Restituisce o esegue lo stream di un file deliverable o grafico PNG generato durante i test con controlli di sicurezza rigorosi.
    """
    if not path or "\x00" in path or ".." in path:
        raise HTTPException(status_code=400, detail="Parametro path non valido")

    if session_id and not SAFE_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="Parametro session_id non valido")

    from src.session_workspace import data_root

    d_root = data_root().resolve()
    sessions_dir = (d_root / "sessions").resolve()
    outputs_dir = OUTPUTS_DIR.resolve()

    target = resolve_diagnostic_file(path, session_id=session_id)
    if not target:
        raise HTTPException(
            status_code=404, detail="File deliverable non trovato o accesso negato"
        )

    try:
        safe_target = target.resolve(strict=True)
    except Exception:
        raise HTTPException(status_code=404, detail="File deliverable non trovato")

    if not safe_target.is_file():
        raise HTTPException(status_code=404, detail="File deliverable non trovato")

    allowed_roots = [sessions_dir.resolve(), outputs_dir.resolve()]
    if not any(safe_target.is_relative_to(base) for base in allowed_roots):
        raise HTTPException(status_code=403, detail="Accesso al path non consentito")

    mime, _ = mimetypes.guess_type(safe_target.name)
    return FileResponse(
        safe_target,
        filename=safe_target.name,
        media_type=mime or "application/octet-stream",
        content_disposition_type="attachment" if download else "inline",
    )


_ACTIVE_TASKS: set[asyncio.Task] = set()


@router.post("/cancel")
async def cancel_diagnostics() -> Dict[str, Any]:
    """Cancels all actively running diagnostic test suites."""
    cancelled = 0
    for t in list(_ACTIVE_TASKS):
        if not t.done():
            t.cancel()
            cancelled += 1
    return {"ok": True, "cancelled": cancelled}


@router.post("/run-tests")
@router.get("/run-tests")
async def run_diagnostics_tests(
    test_id: Optional[str] = Query(None, description="Run only a specific test ID"),
    profile: Optional[str] = Query(
        None, description="Profile slug or name to run the tests against"
    ),
):
    """
    Executes the Agent Smoke Test suite sequentially and streams status events via SSE with input validation.
    """
    if test_id and not SAFE_ID_RE.fullmatch(test_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid test_id parameter (alphanumeric, dash, underscore only)",
        )

    if profile and not SAFE_ID_RE.fullmatch(profile):
        raise HTTPException(
            status_code=400,
            detail="Invalid profile parameter (alphanumeric, dash, underscore only)",
        )

    import asyncio
    from evals.agent_smoke_tests.test_runner import run_smoke_tests_stream

    async def event_generator():
        current_task = asyncio.current_task()
        if current_task:
            _ACTIVE_TASKS.add(current_task)
        try:
            async for evt in run_smoke_tests_stream(
                test_id=test_id,
                profile=profile,
                config_path=CONFIG_FILE,
                outputs_dir=OUTPUTS_DIR,
            ):
                yield {"event": "message", "data": json.dumps(evt, ensure_ascii=False)}
        except asyncio.CancelledError:
            logger.info("Diagnostics test run cancelled by user.")
            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "step": "suite_cancelled",
                        "message": "Esecuzione test interrotta dall'utente.",
                    },
                    ensure_ascii=False,
                ),
            }
        except Exception as ex:
            logger.exception("Error in diagnostics SSE event generator: %s", ex)
            yield {
                "event": "error",
                "data": json.dumps(
                    {"status": "failed", "error": str(ex)}, ensure_ascii=False
                ),
            }
        finally:
            if current_task and current_task in _ACTIVE_TASKS:
                _ACTIVE_TASKS.discard(current_task)

    return EventSourceResponse(
        event_generator(),
        ping=15,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
