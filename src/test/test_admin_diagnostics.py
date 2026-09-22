import asyncio
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import src.aion_env  # noqa: F401
from src.api.admin_diagnostics import (
    get_test_config,
    list_reports,
    get_report_content,
)
from evals.agent_smoke_tests.test_runner import (
    format_markdown_report,
    resolve_asset_path,
)


def test_test_config_loading():
    """Verify that test_config.json contains the 3 expected test scenarios."""
    config = asyncio.run(get_test_config())
    assert isinstance(config, list)
    assert len(config) == 3

    ids = [c["id"] for c in config]
    assert "test_1_excel" in ids
    assert "test_2_pdf" in ids
    assert "test_3_word" in ids

    for c in config:
        assert c["assistant"] == "generic_assistant"
        assert len(c["prompt"]) > 10


def test_asset_resolver():
    """Verify that asset paths resolve correctly."""
    excel_path = resolve_asset_path("assets/dataset_vendite.xlsx")
    assert excel_path is not None
    assert excel_path.exists()
    assert excel_path.suffix.lower() == ".xlsx"

    pdf_path = resolve_asset_path("assets/manuale_tesla.pdf")
    assert pdf_path is not None
    assert pdf_path.exists()
    assert pdf_path.suffix.lower() == ".pdf"


def test_markdown_report_formatting():
    """Verify the generated Markdown matches the required specification."""
    fake_results = [
        {
            "id": "test_1_excel",
            "name": "Analisi Dati Excel",
            "assistant": "generic_assistant",
            "duration_sec": 12.5,
            "status": "completed",
            "reasoning": "Ragionamento sul dataset...",
            "tool_calls": [
                {
                    "name": "sandbox_exec",
                    "parameters": {"code": "import pandas as pd"},
                }
            ],
            "final_output": "Ecco i KPI calcolati.",
        }
    ]

    report = format_markdown_report(fake_results, execution_mode="sequential")
    assert "## Test test_1_excel: Analisi Dati Excel" in report
    assert "**Assistente:** Generic Assistant" in report
    assert "**Tempo di esecuzione:** 12.5s" in report
    assert "### 🧠 Reasoning" in report
    assert "Ragionamento sul dataset..." in report
    assert "### 🛠️ Tool Calls" in report
    assert "- **Tool:** `sandbox_exec`" in report
    assert "### 📝 Output Finale" in report
    assert "Ecco i KPI calcolati." in report


def test_diagnostics_report_endpoints(tmp_path, monkeypatch):
    """Test reports listing and reading endpoints."""
    from src.api.admin_diagnostics import router
    from fastapi import FastAPI

    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    report_file = outputs_dir / "report_smoke_test_20260921_120000.md"
    report_file.write_text("# Test Report\nContent here", encoding="utf-8")

    monkeypatch.setattr("src.api.admin_diagnostics.OUTPUTS_DIR", outputs_dir)

    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        # List reports
        res = client.get("/diagnostics/reports")
        assert res.status_code == 200
        reports = res.json()
        assert len(reports) == 1
        assert reports[0]["filename"] == "report_smoke_test_20260921_120000.md"

        # Get specific report content
        res_detail = client.get(
            "/diagnostics/reports/report_smoke_test_20260921_120000.md"
        )
        assert res_detail.status_code == 200
        data = res_detail.json()
        assert data["filename"] == "report_smoke_test_20260921_120000.md"
        assert "# Test Report" in data["content"]


def test_single_test_markdown_and_timeline(tmp_path):
    """Verify single test standalone report and chronological timeline interleaving."""
    from evals.agent_smoke_tests.test_runner import format_single_test_markdown

    test_res = {
        "id": "test_3_word",
        "name": "Generazione Word Strutturato",
        "assistant": "generic_assistant",
        "prompt": "Genera agenda_kickoff.docx",
        "duration_sec": 18.4,
        "status": "completed",
        "tool_calls": [{"name": "sandbox_write_workspace_file"}],
        "timeline": [
            {
                "type": "reasoning",
                "content": "Devo creare il documento Word con la tabella richiesta.",
            },
            {
                "type": "tool_call",
                "name": "sandbox_write_workspace_file",
                "parameters": {"relative_path": "workspace/make_doc.py"},
                "status": "success",
                "result": "File scritto",
            },
            {
                "type": "reasoning",
                "content": "Ora eseguo lo script per compilare agenda_kickoff.docx.",
            },
            {
                "type": "tool_call",
                "name": "sandbox_run_python_file",
                "parameters": {"relative_path": "workspace/make_doc.py"},
                "status": "success",
                "result": "Exit code 0",
            },
        ],
        "generated_files": [
            {
                "name": "agenda_kickoff.docx",
                "category": "Documento",
                "size_bytes": 12400,
                "relative_to_outputs": "generated_files/test_3_word/agenda_kickoff.docx",
                "file_url": "file:///C:/outputs/generated_files/test_3_word/agenda_kickoff.docx",
                "is_image": False,
            }
        ],
        "final_output": "Documento agenda_kickoff.docx generato con successo.",
    }

    report = format_single_test_markdown(test_res, tmp_path)
    assert "# Smoke Test Report: Generazione Word Strutturato" in report
    assert "### 📁 Documenti & File" in report
    assert "agenda_kickoff.docx" in report
    assert "### ⏱️ Flusso di Esecuzione Cronologico (Timeline)" in report
    assert "Passo 1 — 🧠 Reasoning" in report
    assert "Passo 2 — 🛠️ Tool: `sandbox_write_workspace_file`" in report
    assert "Passo 3 — 🧠 Reasoning" in report
    assert "Passo 4 — 🛠️ Tool: `sandbox_run_python_file`" in report
    assert "### 📝 Risposta Finale dell'Agente" in report
    assert "Documento agenda_kickoff.docx generato con successo." in report


def test_diagnostics_file_endpoint(tmp_path, monkeypatch):
    """Verify /diagnostics/file resolves and serves diagnostic files."""
    from src.api.admin_diagnostics import router
    from fastapi import FastAPI

    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    sample_file = outputs_dir / "sample_chart.png"
    sample_file.write_bytes(b"\x89PNG\r\n\x1a\nfake_image_data")

    monkeypatch.setattr("src.api.admin_diagnostics.OUTPUTS_DIR", outputs_dir)

    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        # 404 for non-existent file
        resp_404 = client.get(
            "/diagnostics/file?path=workspace/non_existent_file_12345.png"
        )
        assert resp_404.status_code == 404

        # 200 for existing file in outputs
        resp_200 = client.get("/diagnostics/file?path=sample_chart.png")
        assert resp_200.status_code == 200
        assert resp_200.headers["content-type"] == "image/png"
        assert resp_200.content == b"\x89PNG\r\n\x1a\nfake_image_data"
