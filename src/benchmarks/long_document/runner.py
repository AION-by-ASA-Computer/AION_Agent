"""Long-document eval runner: doc_ingest + grep against YAML golden cases."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from src.tools.doc_ingest import ingest_document

from .scoring import score_identity_gate, score_required_hits
from .synthetic import build_rumore_decreto_pdf

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES_DIR = REPO_ROOT / "evals" / "long_document" / "cases"


def load_dataset(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    if p.suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(raw) or {}
    else:
        data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"dataset must be a mapping: {p}")
    return data


def _resolve_pdf(case: dict[str, Any], work_dir: Path) -> Path | None:
    pdf = case.get("pdf") or {}
    source = str(pdf.get("source") or "synthetic")

    if source == "synthetic":
        profile = str(pdf.get("profile") or "rumore_decreto")
        if profile != "rumore_decreto":
            raise ValueError(f"unknown synthetic pdf profile: {profile}")
        out = work_dir / str(pdf.get("filename") or "synthetic_decreto.pdf")
        return build_rumore_decreto_pdf(
            out,
            pages=int(pdf.get("pages") or 200),
            prescription_page=int(pdf.get("prescription_page") or 101),
            pmc_page=int(pdf.get("pmc_page") or 150),
        )

    if source == "env":
        env_name = str(pdf.get("path_env") or "AION_EVAL_LONG_DOC_PDF")
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        return path if path.is_file() else None

    if source == "path":
        path = Path(str(pdf.get("path") or "")).expanduser()
        return path if path.is_file() else None

    raise ValueError(f"unsupported pdf.source: {source}")


async def _ingest_until_complete(
    pdf_path: Path,
    session_root: Path,
    ingest_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Call doc_ingest until ``partial`` is false (resume-friendly)."""
    first = int(ingest_cfg.get("first_page") or 1)
    last = int(ingest_cfg.get("last_page") or 0)
    budget = float(ingest_cfg.get("budget_sec") or 600)
    ocr_mode = str(ingest_cfg.get("ocr_mode") or "never")
    force = bool(ingest_cfg.get("force") or False)
    write_full = bool(ingest_cfg.get("write_full") or False)

    manifest: dict[str, Any] = {"ok": False}
    resume_from = first
    for _ in range(50):
        manifest = await ingest_document(
            pdf_path,
            session_root,
            first_page=resume_from,
            last_page=last,
            ocr_mode=ocr_mode,
            budget_sec=budget,
            force=force,
            write_full=write_full,
        )
        if not manifest.get("ok"):
            return manifest
        if not manifest.get("partial"):
            return manifest
        nxt = manifest.get("resume_from")
        if not nxt or int(nxt) <= resume_from:
            return manifest
        resume_from = int(nxt)
    manifest["warning"] = "ingest stopped after 50 resume iterations"
    return manifest


async def run_pipeline_case(
    case: dict[str, Any],
    *,
    work_dir: Path,
) -> dict[str, Any]:
    """Run ingest + scoring for a single YAML case."""
    case_id = str(case.get("id") or "case")
    pdf_path = _resolve_pdf(case, work_dir)
    if pdf_path is None:
        skipped = bool(case.get("skip_if_pdf_missing", True))
        return {
            "case_id": case_id,
            "skipped": skipped,
            "reason": "pdf not available (set env or path)",
            "recall": None,
            "passed": None if skipped else False,
        }

    session_root = work_dir / "session"
    session_root.mkdir(parents=True, exist_ok=True)
    uploads = session_root / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    linked = uploads / pdf_path.name
    if not linked.exists():
        try:
            linked.hardlink_to(pdf_path)
        except OSError:
            import shutil

            shutil.copy2(pdf_path, linked)

    ingest_cfg = case.get("ingest") or {}
    manifest = await _ingest_until_complete(linked, session_root, ingest_cfg)
    if not manifest.get("ok"):
        return {
            "case_id": case_id,
            "skipped": False,
            "passed": False,
            "recall": 0.0,
            "error": manifest,
        }

    slug = str(manifest["slug"])
    hit_score = score_required_hits(
        session_root,
        slug,
        list(case.get("required_hits") or []),
    )
    identity_score = score_identity_gate(manifest, case.get("identity") or {})

    passed = (
        hit_score["recall"] >= float(case.get("min_recall") or 1.0)
        and identity_score["passed"]
    )
    return {
        "case_id": case_id,
        "skipped": False,
        "passed": passed,
        "recall": hit_score["recall"],
        "slug": slug,
        "manifest": {
            "pages_total": manifest.get("pages_total"),
            "pages_written": manifest.get("pages_written"),
            "partial": manifest.get("partial"),
            "title_guess": manifest.get("title_guess"),
        },
        "hits": hit_score,
        "identity": identity_score,
    }


async def run_long_document_pipeline_eval(
    dataset_path: str | Path,
    *,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """Evaluate all cases in a dataset directory or single YAML file."""
    path = Path(dataset_path)
    if path.is_dir():
        case_files = sorted(path.glob("*.yaml")) + sorted(path.glob("*.yml"))
    else:
        case_files = [path]

    root_work = work_dir or (REPO_ROOT / "data" / "eval_runs" / "long_document")
    root_work.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for case_file in case_files:
        dataset = load_dataset(case_file)
        cases = dataset.get("cases")
        if cases is None:
            cases = [dataset]
        for case in cases:
            case_work = root_work / str(case.get("id") or case_file.stem)
            case_work.mkdir(parents=True, exist_ok=True)
            row = await run_pipeline_case(case, work_dir=case_work)
            row["dataset"] = str(case_file)
            results.append(row)

    scored = [r for r in results if not r.get("skipped")]
    skipped = [r for r in results if r.get("skipped")]
    passed = [r for r in scored if r.get("passed")]
    recall_vals = [float(r["recall"]) for r in scored if r.get("recall") is not None]

    metrics = {
        "case_count": len(results),
        "scored_count": len(scored),
        "skipped_count": len(skipped),
        "passed_count": len(passed),
        "accuracy_overall": (len(passed) / len(scored)) if scored else 1.0,
        "mean_recall": (sum(recall_vals) / len(recall_vals)) if recall_vals else 1.0,
        "results": results,
    }
    return metrics
