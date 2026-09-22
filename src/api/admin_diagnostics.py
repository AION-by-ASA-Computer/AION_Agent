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

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger("aion.api.diagnostics")

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SMOKE_TESTS_DIR = REPO_ROOT / "evals" / "agent_smoke_tests"
CONFIG_FILE = SMOKE_TESTS_DIR / "test_config.json"
OUTPUTS_DIR = SMOKE_TESTS_DIR / "outputs"


class RunTestsRequest(BaseModel):
    test_id: Optional[str] = None


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
    for p in sorted(
        OUTPUTS_DIR.glob("report_*.md"), key=lambda x: x.stat().st_mtime, reverse=True
    ):
        st = p.stat()
        reports.append(
            {
                "filename": p.name,
                "size_bytes": st.st_size,
                "modified_at": datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    return reports


@router.get("/reports/{filename}")
async def get_report_content(filename: str) -> Dict[str, Any]:
    """Returns the content of a specific test report."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    target = OUTPUTS_DIR / filename
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Report file not found")

    try:
        content = target.read_text(encoding="utf-8")
        st = target.stat()
        return {
            "filename": filename,
            "content": content,
            "size_bytes": st.st_size,
            "modified_at": datetime.fromtimestamp(
                st.st_mtime, tz=timezone.utc
            ).isoformat(),
        }
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {ex}")


def resolve_diagnostic_file(
    raw_path: str, session_id: Optional[str] = None
) -> Optional[Path]:
    """
    Risolve in modo sicuro file/immagini generati durante le sessioni di test fumo.
    Supporta URI file://, path assoluti/relativi sessione (data/sessions/.../workspace/...),
    path workspace diretti o semplici nomi file cercandoli nell'ultima sessione smoke.
    """
    from src.session_workspace import data_root

    clean = (raw_path or "").strip().replace("\\", "/")
    clean = re.sub(r"^file:/*(app/)?", "", clean)
    clean = clean.lstrip("/")

    if not clean or ".." in clean:
        return None

    d_root = data_root()
    sessions_dir = d_root / "sessions"

    # 1. Path strutturato con prefisso sessions/
    if clean.startswith("data/sessions/") or clean.startswith("sessions/"):
        rel = clean.split("sessions/", 1)[1]
        base_sessions = sessions_dir.resolve()
        target = (base_sessions / rel).resolve()
        try:
            target.relative_to(base_sessions)
        except ValueError:
            return None
        if target.is_file() and target.exists():
            return target

    # 2. Se viene specificato un session_id
    if session_id:
        target = (sessions_dir / session_id / clean).resolve()
        if target.is_file() and target.exists():
            return target
        target_ws = (sessions_dir / session_id / "workspace" / clean).resolve()
        if target_ws.is_file() and target_ws.exists():
            return target_ws
        target_der = (sessions_dir / session_id / "derived" / clean).resolve()
        if target_der.is_file() and target_der.exists():
            return target_der

    # 3. Controlla in outputs/
    if OUTPUTS_DIR.exists():
        target_out = (OUTPUTS_DIR / clean).resolve()
        if target_out.is_file() and target_out.exists():
            return target_out

    # 4. Cerca nelle directory sessioni smoke recenti
    filename = Path(clean).name
    if filename and sessions_dir.exists():
        for s_dir in sorted(
            sessions_dir.glob("smoke_*"), key=lambda x: x.stat().st_mtime, reverse=True
        ):
            for candidate in [
                s_dir / "workspace" / filename,
                s_dir / "derived" / filename,
                s_dir / "uploads" / filename,
                s_dir / clean,
            ]:
                if candidate.is_file() and candidate.exists():
                    return candidate

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
    Restituisce o esegue lo stream di un file deliverable o grafico PNG generato durante i test.
    """
    target = resolve_diagnostic_file(path, session_id=session_id)
    if not target or not target.is_file() or not target.exists():
        raise HTTPException(status_code=404, detail="File deliverable non trovato")

    mime, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        target,
        filename=target.name,
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
):
    """
    Executes the Agent Smoke Test suite sequentially and streams status events via SSE.
    """
    import asyncio
    from evals.agent_smoke_tests.test_runner import run_smoke_tests_stream

    async def event_generator():
        current_task = asyncio.current_task()
        if current_task:
            _ACTIVE_TASKS.add(current_task)
        try:
            async for evt in run_smoke_tests_stream(
                test_id=test_id,
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
