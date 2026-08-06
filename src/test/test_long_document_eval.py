"""Eval harness tests for long-document extraction (pipeline + dataset schema)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from src.benchmarks.long_document.runner import (
    DEFAULT_CASES_DIR,
    load_dataset,
    run_long_document_pipeline_eval,
    run_pipeline_case,
)
from src.benchmarks.long_document.scoring import (
    page_no_from_hit_file,
    score_identity_gate,
    score_required_hits,
)
from src.benchmarks.long_document.synthetic import build_rumore_decreto_pdf
from src.tools.doc_ingest import ingest_document

SYNTHETIC = DEFAULT_CASES_DIR / "synthetic_smoke.yaml"
ALTOMONTE = DEFAULT_CASES_DIR / "altomonte_rumore.yaml"


def _validate_case(case: dict, *, path: Path) -> None:
    assert case.get("id"), f"{path}: case missing id"
    pdf = case.get("pdf") or {}
    assert pdf.get("source") in {"synthetic", "env", "path"}, (
        f"{case['id']}: invalid pdf.source"
    )
    for hit in case.get("required_hits") or []:
        assert hit.get("grep_pattern"), f"{case['id']}: hit missing grep_pattern"


@pytest.mark.parametrize("path", [SYNTHETIC, ALTOMONTE])
def test_long_document_dataset_schema(path: Path):
    assert path.is_file(), f"missing {path}"
    data = load_dataset(path)
    cases = data.get("cases") or [data]
    assert cases, f"{path}: no cases"
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), f"{path}: duplicate case ids"
    for case in cases:
        _validate_case(case, path=path)


def test_page_no_from_hit_file():
    assert page_no_from_hit_file("derived/docs/foo/pages/p0101.txt") == 101
    assert page_no_from_hit_file("p0042.txt") == 42
    assert page_no_from_hit_file("readme.txt") is None


@pytest.mark.asyncio
async def test_synthetic_smoke_pipeline_eval_passes(tmp_path):
    metrics = await run_long_document_pipeline_eval(SYNTHETIC, work_dir=tmp_path)
    assert metrics["scored_count"] == 1
    assert metrics["passed_count"] == 1
    assert metrics["accuracy_overall"] == 1.0
    assert metrics["mean_recall"] == 1.0


@pytest.mark.asyncio
async def test_altomonte_cases_skip_without_pdf(tmp_path, monkeypatch):
    monkeypatch.delenv("AION_EVAL_ALTOMONTE_PDF", raising=False)
    metrics = await run_long_document_pipeline_eval(ALTOMONTE, work_dir=tmp_path)
    assert metrics["case_count"] == 2
    assert metrics["skipped_count"] == 2
    assert metrics["scored_count"] == 0


@pytest.mark.asyncio
async def test_scoring_required_hits_on_ingested_pages(tmp_path):
    pdf = build_rumore_decreto_pdf(tmp_path / "decreto.pdf", pages=20, prescription_page=10, pmc_page=15)
    session = tmp_path / "session"
    manifest = await ingest_document(pdf, session, ocr_mode="never", budget_sec=60)
    assert manifest["ok"]

    score = score_required_hits(
        session,
        manifest["slug"],
        [
            {
                "label": "pic53",
                "grep_pattern": "\\[53\\]",
                "page": 10,
                "must_contain": ["[53]", "rumore"],
            }
        ],
    )
    assert score["recall"] == 1.0
    assert score["details"][0]["passed"]


def test_identity_gate_detects_wrong_plant():
    manifest = {
        "title_guess": "Decreto impianto Altomonte",
        "first_page_excerpt": "Centrale termoelettrica Altomonte",
        "source": "decreto.pdf",
    }
    ok = score_identity_gate(
        manifest,
        {"must_contain": ["altomonte"], "must_not_contain": ["presenzano"]},
    )
    assert ok["passed"] is True

    bad = score_identity_gate(
        manifest,
        {"must_contain": ["presenzano"], "must_not_contain": []},
    )
    assert bad["passed"] is False
    assert "presenzano" in bad["missing"]


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("AION_EVAL_LLM"),
    reason="Set AION_EVAL_LLM=1 to run agentic long-document eval",
)
async def test_agentic_altomonte_optional(tmp_path):
    """End-to-end agent eval — requires LLM, OCR service, and AION_EVAL_ALTOMONTE_PDF."""
    from src.agent_pipeline import AgentPipeline
    from src.benchmarks.long_document.scoring import score_agent_output
    from src.main import get_agent, set_event_loop

    pdf_env = os.getenv("AION_EVAL_ALTOMONTE_PDF", "").strip()
    if not pdf_env or not Path(pdf_env).is_file():
        pytest.skip("AION_EVAL_ALTOMONTE_PDF not set")

    data = yaml.safe_load(ALTOMONTE.read_text(encoding="utf-8"))
    case = data["cases"][0]
    session_id = f"eval_{case['id']}"
    set_event_loop(__import__("asyncio").get_event_loop())

    # Seed session with ingested PDF via pipeline eval helper first.
    await run_pipeline_case(case, work_dir=tmp_path / "seed")

    agent, profile = await get_agent("document_extractor", session_id=session_id, user_id="eval")
    pipeline = AgentPipeline(
        agent, session_id=session_id, profile_name=profile, user_id="eval"
    )
    agent_cfg = case.get("agent_expectations") or {}
    res = await pipeline.run(str(agent_cfg.get("user_query") or ""))
    scored = score_agent_output(res.get("text", ""), agent_cfg)
    assert scored["passed"], scored
