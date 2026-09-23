"""
Unit tests for the deterministic smoke test evaluator (evals/agent_smoke_tests/evaluator.py).
Validates 0-100 scoring, 10 micro-criteria per test, ratings, and assertions.
"""

from pathlib import Path
from evals.agent_smoke_tests.evaluator import (
    evaluate_test,
    evaluate_excel_test,
    evaluate_pdf_test,
    evaluate_word_test,
    _calc_rating,
)


def test_calc_rating():
    assert _calc_rating(95) == ("A+", True)
    assert _calc_rating(90) == ("A+", True)
    assert _calc_rating(85) == ("A", True)
    assert _calc_rating(75) == ("B", True)
    assert _calc_rating(65) == ("C", True)
    assert _calc_rating(60) == ("C", True)
    assert _calc_rating(59) == ("F", False)
    assert _calc_rating(0) == ("F", False)


def test_evaluate_excel_full_points(tmp_path: Path):
    session_dir = tmp_path / "session_1"
    ws = session_dir / "workspace"
    ws.mkdir(parents=True)

    # Mock tool calls and final output with all correct numbers
    test_result = {
        "id": "test_1_excel",
        "status": "completed",
        "tool_calls": [
            {
                "tool": "sandbox_run_python_file",
                "parameters": {"relative_path": "workspace/analyze.py"},
            },
            {
                "tool": "render_chart",
                "parameters": {"type": "bar", "title": "Vendite per Agente 2025"},
            },
        ],
        "final_output": (
            "Ecco il report vendite:\n"
            "Il fatturato 2025 ammonta a 497.412 € con un margine di 275.682 € e un AOV di 3.502,90 €.\n"
            "Il miglior agente è Alessandro Riva con oltre 126.000 €.\n"
            "Il mese di picco è Maggio con 59.670 €.\n"
            "La classifica top SKU vede in testa SECURITY-AUDIT e SAAS-PLATFORM che rispettano il principio di Pareto 80/20.\n"
            "Tabella riassuntiva:\n"
            "| Metrica | Valore |\n"
            "| --- | --- |\n"
            "| Fatturato 2025 | 497.412 € |\n"
            "| Margine | 275.682 € |\n\n"
            "Key Takeaways e Sintesi:\n"
            "- Il fatturato 2025 è trainato dalle vendite di Maggio.\n"
            "- Alessandro Riva è il top performer aziendale.\n"
            "- I primi due SKU generano la maggioranza della marginalità.\n"
        ),
        "duration_sec": 15.0,
    }

    eval_res = evaluate_excel_test(
        test_result, session_id="session_1", session_dir=session_dir
    )

    assert eval_res.test_id == "test_1_excel"
    assert eval_res.score == 100
    assert eval_res.rating == "A+"
    assert eval_res.passed is True
    assert len(eval_res.criteria) == 10
    assert all(c.passed for c in eval_res.criteria)


def test_evaluate_pdf_rag(tmp_path: Path):
    session_dir = tmp_path / "session_2"
    session_dir.mkdir(parents=True)

    test_result = {
        "id": "test_2_pdf",
        "status": "completed",
        "tool_calls": [
            {
                "tool": "pdf_evidence_search",
                "parameters": {"query": "apertura portiere"},
            },
            {
                "tool": "pdf_evidence_search",
                "parameters": {"query": "freni frenata emergenza"},
            },
        ],
        "final_output": (
            "Ecco la procedura di apertura porte e frenata per Tesla Model 3 estratta dal manuale ufficiale:\n"
            "Sezione 'Apertura e chiusura':\n"
            "1. Apertura Portiere Anteriori: Premere il pulsante sopra la maniglia interna. In caso di emergenza o assenza di alimentazione elettrica, tirare lo sblocco manuale meccanico situato davanti ai comandi del finestrino (pagina 14).\n"
            "2. Apertura Portiere Posteriori: Utilizzare il cavo di rilascio meccanico situato sotto la tasca della portiera o griglia dell'altoparlante (pagina 15).\n"
            "Sezione 'Manutenzione e freni':\n"
            "3. Manutenzione Liquido Freni: Il controllo deve avvenire ogni 2 anni verificando la percentuale di umidità e contaminazione (ebollizione > 180°C) oppure sostituzione programmata ogni 4 anni.\n"
        ),
        "duration_sec": 12.0,
    }

    eval_res = evaluate_pdf_test(
        test_result, session_id="session_2", session_dir=session_dir
    )

    assert eval_res.test_id == "test_2_pdf"
    assert eval_res.score >= 90
    assert eval_res.passed is True
    assert len(eval_res.criteria) == 10


def test_evaluate_word_generation(tmp_path: Path):
    session_dir = tmp_path / "session_3"
    ws = session_dir / "workspace"
    ws.mkdir(parents=True)

    # Create dummy docx file
    docx_file = ws / "agenda_kickoff.docx"
    import zipfile

    xml_content = (
        "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
        "<w:body>"
        "<w:p><w:r><w:t>Kickoff Meeting Agenda - Progetto Alpha</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Data: 15 Ottobre 2026</w:t></w:r></w:p>"
        "<w:tbl>"
        "<w:tr><w:tc><w:p><w:r><w:t>Orario</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Argomento</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Relatore</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>09:00 - 09:30</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Benvenuto</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>PM</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>09:30 - 10:30</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Obiettivi</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Tech Lead</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>10:30 - 11:00</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Q&amp;A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Team</w:t></w:r></w:p></w:tc></w:tr>"
        "</w:tbl>"
        "<w:p><w:r><w:t>Materiali preparatori richiesti:</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>- Documento dei requisiti</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>- Architettura di massima</w:t></w:r></w:p>"
        "</w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(docx_file, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types></Types>")
        # add padding so size is > 3000 bytes
        zf.writestr("word/document.xml", xml_content + "<!-- " + "x" * 3500 + " -->")

    test_result = {
        "id": "test_3_word",
        "status": "completed",
        "tool_calls": [
            {
                "tool": "sandbox_run_python_file",
                "parameters": {"relative_path": "workspace/create_word.py"},
            },
        ],
        "final_output": (
            "Ho creato il documento Word `agenda_kickoff.docx` per la riunione del 15 Ottobre contenente:\n"
            "- Titolo: Kickoff Meeting Agenda Progetto Alpha\n"
            "- Tabella oraria strutturata con colonne Orario, Argomento, Relatore\n"
            "- Sezione Materiali preparatori con elenco puntato dei documenti richiesti\n"
        ),
        "duration_sec": 10.0,
    }

    eval_res = evaluate_word_test(
        test_result, session_id="session_3", session_dir=session_dir
    )

    assert eval_res.test_id == "test_3_word"
    assert eval_res.score >= 90
    assert eval_res.passed is True
    assert len(eval_res.criteria) == 10


def test_evaluate_test_router():
    res = evaluate_test(
        "test_1_excel",
        {
            "id": "test_1_excel",
            "status": "failed",
            "error": "Timeout occurred",
            "tool_calls": [],
            "final_output": "",
        },
    )
    assert res.test_id == "test_1_excel"
    assert res.score == 0
    assert res.passed is False
    assert res.rating == "F"
