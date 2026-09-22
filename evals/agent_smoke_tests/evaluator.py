#!/usr/bin/env python3
"""
Static Assertions & Scoring Engine for AION Agent Smoke Tests.
Calculates deterministic scores (0-100) and granular micro-criteria without LLM-as-a-Judge.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CriterionResult:
    id: str
    name: str
    category: str  # "tool", "data", "file", "formatting"
    points: int
    max_points: int
    passed: bool
    details: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "points": self.points,
            "max_points": self.max_points,
            "points_awarded": self.points,
            "points_max": self.max_points,
            "passed": self.passed,
            "details": self.details,
        }


@dataclass
class EvaluationResult:
    test_id: str
    score: int
    max_score: int
    rating: str  # "A+" | "A" | "B" | "C" | "F"
    passed: bool
    summary: str
    criteria: List[CriterionResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "score": self.score,
            "max_score": self.max_score,
            "rating": self.rating,
            "passed": self.passed,
            "summary": self.summary,
            "criteria": [c.to_dict() for c in self.criteria],
        }


def _calc_rating(score: int) -> Tuple[str, bool]:
    if score >= 90:
        return "A+", True
    elif score >= 80:
        return "A", True
    elif score >= 70:
        return "B", True
    elif score >= 60:
        return "C", True
    return "F", False


def _normalize_text(text: str) -> str:
    """Normalizes text for keyword and regex matching."""
    return re.sub(r"\s+", " ", text.lower().replace(",", "."))


def _extract_numbers(text: str) -> List[float]:
    """Extracts all floats/integers from text, handling EU and US currency notation."""
    cleaned = re.sub(r"[€$£kK\s]", "", text)
    # Find patterns like 123.456,78 or 123,456.78 or 123456.78
    tokens = re.findall(r"\b\d+(?:[\.,]\d+)?\b", text)
    nums = []
    for t in tokens:
        try:
            val = float(t.replace(",", "."))
            nums.append(val)
        except ValueError:
            pass
    return nums


def _has_approx_number(text: str, target: float, tolerance_pct: float = 2.0) -> bool:
    """Checks if target number appears in text within tolerance percentage or standard thousands."""
    t_min = target * (1.0 - tolerance_pct / 100.0)
    t_max = target * (1.0 + tolerance_pct / 100.0)

    # Direct digit match ignoring dots
    # e.g. 497412 -> matches 497.412 or 497,412 or 497412
    target_int = int(round(target))
    target_str_no_sep = str(target_int)
    target_thousands_eu = f"{target_int:,}".replace(",", ".")
    target_thousands_us = f"{target_int:,}"

    if (
        target_str_no_sep in text
        or target_thousands_eu in text
        or target_thousands_us in text
        or f"{target_int//1000}k" in text.lower()
        or f"{target_int//1000} k" in text.lower()
    ):
        return True

    # Scan extracted numbers
    for num in _extract_numbers(text):
        if t_min <= num <= t_max:
            return True

    return False


def _inspect_docx(file_path: Path) -> Dict[str, Any]:
    """Inspects a .docx file structure via zipfile and XML without external dependencies."""
    res = {
        "valid": False,
        "size_bytes": 0,
        "paragraphs": [],
        "text_content": "",
        "tables_count": 0,
        "table_headers": [],
        "table_row_count": 0,
    }
    if not file_path.exists() or not file_path.is_file():
        return res

    res["size_bytes"] = file_path.stat().st_size
    try:
        with zipfile.ZipFile(file_path, "r") as z:
            if "word/document.xml" not in z.namelist():
                return res
            xml_data = z.read("word/document.xml")
            tree = ET.fromstring(xml_data)

        res["valid"] = True
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

        # Extract paragraphs
        paragraphs = []
        for p in tree.findall(".//w:p", ns):
            texts = [t.text for t in p.findall(".//w:t", ns) if t.text]
            p_text = "".join(texts).strip()
            if p_text:
                paragraphs.append(p_text)
        res["paragraphs"] = paragraphs
        res["text_content"] = "\n".join(paragraphs)

        # Extract tables
        tables = tree.findall(".//w:tbl", ns)
        res["tables_count"] = len(tables)

        if tables:
            first_table = tables[0]
            rows = first_table.findall(".//w:tr", ns)
            res["table_row_count"] = len(rows)
            if rows:
                header_row = rows[0]
                cells = header_row.findall(".//w:tc", ns)
                headers = []
                for c in cells:
                    c_texts = [t.text for t in c.findall(".//w:t", ns) if t.text]
                    headers.append("".join(c_texts).strip())
                res["table_headers"] = headers

    except Exception:
        res["valid"] = False

    return res


def evaluate_excel_test(
    test_result: Dict[str, Any], session_id: str, session_dir: Optional[Path]
) -> EvaluationResult:
    """Evaluates Test 1: Analisi Dati Excel (100 pt)."""
    criteria: List[CriterionResult] = []
    output_text = test_result.get("final_output", "") + " " + test_result.get("reasoning", "")
    tool_calls = test_result.get("tool_calls", [])
    gen_files = test_result.get("generated_files", [])

    # Find PNG images in workspace
    png_files = [f for f in gen_files if f.get("name", "").lower().endswith(".png") or f.get("is_image")]
    if not png_files and session_dir and session_dir.exists():
        ws_dir = session_dir / "workspace"
        if ws_dir.exists():
            png_files = [{"name": p.name, "size_bytes": p.stat().st_size} for p in ws_dir.rglob("*.png")]

    # 1. Tool execution (10 pt)
    python_calls = [
        tc for tc in tool_calls
        if (tc.get("tool") or tc.get("name") or "") in ["sandbox_run_python_file", "sandbox_execute_python", "sandbox_write_workspace_file"]
    ]
    has_tool = len(python_calls) > 0
    criteria.append(
        CriterionResult(
            id="tool_sandbox",
            name="Esecuzione Sandbox Python",
            category="tool",
            points=10 if has_tool else 0,
            max_points=10,
            passed=has_tool,
            details=f"Invocati {len(python_calls)} tool sandbox per calcoli e grafici" if has_tool else "Nessuna esecuzione sandbox rilevata",
        )
    )

    # 2. Fatturato Netto (15 pt) (~497.412 € nel 2025 o ~954.925 € totale)
    has_net_rev = (
        _has_approx_number(output_text, 497412.0)
        or _has_approx_number(output_text, 954925.5)
        or "497" in output_text
        or "954" in output_text
    )
    criteria.append(
        CriterionResult(
            id="kpi_net_revenue",
            name="Fatturato Netto Totale / 2025",
            category="data",
            points=15 if has_net_rev else 0,
            max_points=15,
            passed=has_net_rev,
            details="Rilevato valore corretto (~497k € 2025 / 954k € Totale)" if has_net_rev else "Valore fatturato netto non trovato o errato",
        )
    )

    # 3. Margine Totale (€) (10 pt) (~275.682 € nel 2025 o ~536.975 € totale)
    has_margin = (
        _has_approx_number(output_text, 275682.0)
        or _has_approx_number(output_text, 536975.5)
        or "275" in output_text
        or "536" in output_text
    )
    criteria.append(
        CriterionResult(
            id="kpi_margin",
            name="Margine Totale (€)",
            category="data",
            points=10 if has_margin else 0,
            max_points=10,
            passed=has_margin,
            details="Rilevato valore margine corretto (~275k € 2025 / 536k € Totale)" if has_margin else "Valore margine totale non trovato",
        )
    )

    # 4. Scontrino Medio (AOV) (10 pt) (~3.502 € nel 2025 o ~3.819 € totale)
    has_aov = (
        _has_approx_number(output_text, 3502.9)
        or _has_approx_number(output_text, 3819.7)
        or "3502" in output_text
        or "3503" in output_text
        or "3819" in output_text
        or "3820" in output_text
        or "3.5" in output_text
        or "3,5" in output_text
        or "3.8" in output_text
        or "3,8" in output_text
    )
    criteria.append(
        CriterionResult(
            id="kpi_aov",
            name="Scontrino Medio (AOV)",
            category="data",
            points=10 if has_aov else 0,
            max_points=10,
            passed=has_aov,
            details="Rilevato AOV corretto (~3.502 € / 3.819 €)" if has_aov else "Valore AOV non trovato",
        )
    )

    # 5. Top Performer Agente (10 pt) -> Alessandro Riva
    has_top_agent = (
        "alessandro riva" in output_text.lower()
        or ("riva" in output_text.lower() and "126" in output_text)
    )
    criteria.append(
        CriterionResult(
            id="top_agent",
            name="Miglior Agente (Alessandro Riva)",
            category="data",
            points=10 if has_top_agent else 0,
            max_points=10,
            passed=has_top_agent,
            details="Identificato correttamente Alessandro Riva come top performer 2025 (~126k €)" if has_top_agent else "Miglior agente non identificato",
        )
    )

    # 6. Trend Mensile / Mese di Picco (10 pt) -> Maggio 2025 / trend
    has_monthly = (
        "maggio" in output_text.lower()
        or "may" in output_text.lower()
        or "2025-05" in output_text
        or "trend mensile" in output_text.lower()
    )
    criteria.append(
        CriterionResult(
            id="monthly_trend",
            name="Trend Mensile / Mese di Picco",
            category="data",
            points=10 if has_monthly else 0,
            max_points=10,
            passed=has_monthly,
            details="Rilevato andamento mensile e picco a Maggio 2025" if has_monthly else "Mese di picco o trend mensile mancante",
        )
    )

    # 7. Top 5 SKU (10 pt)
    sku_matches = sum(
        1 for sku in ["security-audit", "gateway-edge", "saas-platform", "training-onboarding", "ai-agent"]
        if sku in output_text.lower()
    )
    has_skus = sku_matches >= 2
    criteria.append(
        CriterionResult(
            id="top_skus",
            name="Classifica Top SKU",
            category="data",
            points=10 if has_skus else 0,
            max_points=10,
            passed=has_skus,
            details=f"Trovati {sku_matches} prodotti top identificati (es. SECURITY-AUDIT)" if has_skus else "Classifica SKU incompleta",
        )
    )

    # 8. Grafico 1: PNG generato o render_chart (10 pt)
    chart_tool_calls = [
        tc for tc in tool_calls
        if (tc.get("tool") or tc.get("name") or "") == "render_chart"
    ]
    has_img1 = len(png_files) >= 1 or len(chart_tool_calls) >= 1
    criteria.append(
        CriterionResult(
            id="chart_bar_agents",
            name="Grafico Performance Agenti (PNG o Chart)",
            category="file",
            points=10 if has_img1 else 0,
            max_points=10,
            passed=has_img1,
            details=f"Generato grafico: {png_files[0]['name'] if png_files else 'render_chart'}" if has_img1 else "Nessun grafico generato",
        )
    )

    # 9. Grafico 2: Secondo PNG generato o secondo render_chart (10 pt)
    has_img2 = (len(png_files) + len(chart_tool_calls)) >= 2 or len(png_files) >= 1 or len(chart_tool_calls) >= 1
    criteria.append(
        CriterionResult(
            id="chart_line_trend",
            name="Grafico Trend Temporale (PNG o Chart)",
            category="file",
            points=10 if has_img2 else 0,
            max_points=10,
            passed=has_img2,
            details="Generato supporto grafico per visualizzazione trend" if has_img2 else "Secondo grafico mancante",
        )
    )

    # 10. Key Takeaways & Formattazione (5 pt)
    has_takeaways = (
        ("takeaway" in output_text.lower() or "sintesi" in output_text.lower() or "punti chiave" in output_text.lower())
        and ("•" in output_text or "-" in output_text or "*" in output_text)
    )
    criteria.append(
        CriterionResult(
            id="formatting_takeaways",
            name="Key Takeaways & Formattazione",
            category="formatting",
            points=5 if has_takeaways else 0,
            max_points=5,
            passed=has_takeaways,
            details="Presenza di 3 bullet point di sintesi operativa ben formattati" if has_takeaways else "Bullet point di sintesi mancanti",
        )
    )

    total_score = sum(c.points for c in criteria)
    rating, passed = _calc_rating(total_score)
    summary = f"{sum(1 for c in criteria if c.passed)}/10 criteri superati ({total_score}/100)"

    return EvaluationResult(
        test_id="test_1_excel",
        score=total_score,
        max_score=100,
        rating=rating,
        passed=passed,
        summary=summary,
        criteria=criteria,
    )


def evaluate_pdf_test(
    test_result: Dict[str, Any], session_id: str, session_dir: Optional[Path]
) -> EvaluationResult:
    """Evaluates Test 2: Estrazione RAG da PDF lungo (100 pt)."""
    criteria: List[CriterionResult] = []
    output_text = test_result.get("final_output", "") + " " + test_result.get("reasoning", "")
    tool_calls = test_result.get("tool_calls", [])

    # 1. Consultazione PDF via Tool (10 pt)
    rag_tools = [
        tc for tc in tool_calls
        if any(k in (tc.get("tool") or tc.get("name") or "").lower() for k in ["pdf", "ocr", "read", "grep", "search", "python"])
    ]
    has_tools = len(rag_tools) > 0
    criteria.append(
        CriterionResult(
            id="tool_pdf_inspection",
            name="Ispezione Documentale PDF",
            category="tool",
            points=10 if has_tools else 0,
            max_points=10,
            passed=has_tools,
            details=f"Invocati {len(rag_tools)} tool di estrazione/lettura sul manuale" if has_tools else "Nessun tool di lettura invocato",
        )
    )

    # 2. Sblocco Portiere Anteriori (15 pt) (maniglia meccanica / levetta davanti pulsanti)
    has_front_door = (
        ("anteriore" in output_text.lower() or "anteriori" in output_text.lower() or "portiera" in output_text.lower())
        and ("meccanic" in output_text.lower() or "levett" in output_text.lower() or "pulsant" in output_text.lower() or "finestrin" in output_text.lower() or "davanti" in output_text.lower())
    )
    criteria.append(
        CriterionResult(
            id="front_door_release",
            name="Sblocco Manuale Portiere Anteriori",
            category="data",
            points=15 if has_front_door else 0,
            max_points=15,
            passed=has_front_door,
            details="Identificata procedura con sblocco meccanico situato davanti ai comandi finestrino" if has_front_door else "Procedura sblocco anteriore non specificata",
        )
    )

    # 3. Sblocco Portiere Posteriori (15 pt) (cavo / levetta sotto tasca o griglia)
    has_rear_door = (
        ("posterior" in output_text.lower() or "posteriore" in output_text.lower())
        and ("cavo" in output_text.lower() or "tasca" in output_text.lower() or "sportellin" in output_text.lower() or "altoparlant" in output_text.lower() or "rilascio" in output_text.lower())
    ) or ("sblocco manuale" in output_text.lower() and "cavo" in output_text.lower())
    criteria.append(
        CriterionResult(
            id="rear_door_release",
            name="Sblocco Manuale Portiere Posteriori",
            category="data",
            points=15 if has_rear_door else 0,
            max_points=15,
            passed=has_rear_door,
            details="Identificata procedura con cavo di rilascio meccanico (tasca/altoparlante)" if has_rear_door else "Procedura portiere posteriori mancante",
        )
    )

    # 4. Frequenza Liquido Freni (Anni) (15 pt) (ogni 2 o 4 anni)
    has_brake_years = (
        ("liquido freni" in output_text.lower() or "freni" in output_text.lower() or "brake" in output_text.lower())
        and ("2 anni" in output_text.lower() or "4 anni" in output_text.lower() or "due anni" in output_text.lower() or "quattro anni" in output_text.lower() or "biennale" in output_text.lower())
    )
    criteria.append(
        CriterionResult(
            id="brake_fluid_years",
            name="Intervallo Temporale Liquido Freni",
            category="data",
            points=15 if has_brake_years else 0,
            max_points=15,
            passed=has_brake_years,
            details="Specificato intervallo di manutenzione (ogni 2 o 4 anni)" if has_brake_years else "Intervallo temporale liquido freni non specificato",
        )
    )

    # 5. Condizione % Umidità / Test Freni (10 pt)
    has_humidity = (
        "umidit" in output_text.lower()
        or "contaminaz" in output_text.lower()
        or "%" in output_text
        or "ebollizion" in output_text.lower()
        or "tester" in output_text.lower()
        or "degrad" in output_text.lower()
    )
    criteria.append(
        CriterionResult(
            id="brake_fluid_humidity",
            name="Criterio % Umidità / Contaminazione",
            category="data",
            points=10 if has_humidity else 0,
            max_points=10,
            passed=has_humidity,
            details="Specificato controllo percentuale umidità/contaminazione liquido freni" if has_humidity else "Dettaglio condizione umidità/test non menzionato",
        )
    )

    # 6. Citazione Pagina Esatta (10 pt)
    has_page = (
        "pagin" in output_text.lower()
        or "pag." in output_text.lower()
        or "p." in output_text.lower()
        or bool(re.search(r"\bpage\s*\d+\b", output_text, re.IGNORECASE))
        or bool(re.search(r"\bpag(?:ina)?\s*\d+\b", output_text, re.IGNORECASE))
    )
    criteria.append(
        CriterionResult(
            id="citation_page",
            name="Citazione Pagina del Manuale",
            category="data",
            points=10 if has_page else 0,
            max_points=10,
            passed=has_page,
            details="Citato esplicitamente il numero di pagina o riferimento" if has_page else "Numero di pagina non citato",
        )
    )

    # 7. Citazione Sezione / Capitolo (10 pt)
    has_section = (
        "sezione" in output_text.lower()
        or "capitolo" in output_text.lower()
        or "manutenzione" in output_text.lower()
        or "apertura" in output_text.lower()
        or "portiere" in output_text.lower()
    )
    criteria.append(
        CriterionResult(
            id="citation_section",
            name="Citazione Sezione / Capitolo",
            category="data",
            points=10 if has_section else 0,
            max_points=10,
            passed=has_section,
            details="Citata sezione ufficiale ('Apertura e chiusura' / 'Manutenzione')" if has_section else "Sezione non citata",
        )
    )

    # 8. Assenza di Errori di Tool (5 pt)
    has_errors = bool(test_result.get("error"))
    criteria.append(
        CriterionResult(
            id="no_tool_errors",
            name="Esecuzione Pulita (Zero Errori)",
            category="tool",
            points=5 if not has_errors else 0,
            max_points=5,
            passed=not has_errors,
            details="Nessun errore fatale durante l'interrogazione" if not has_errors else f"Rilevato errore: {test_result.get('error')}",
        )
    )

    # 9. Chiarezza e Struttura Procedurale (5 pt)
    has_clarity = len(output_text.strip()) >= 200 and ("1." in output_text or "•" in output_text or "-" in output_text)
    criteria.append(
        CriterionResult(
            id="procedural_clarity",
            name="Struttura Passo-Passo della Risposta",
            category="formatting",
            points=5 if has_clarity else 0,
            max_points=5,
            passed=has_clarity,
            details="Risposta strutturata ed esaustiva per l'utente finale" if has_clarity else "Risposta troppo breve o poco strutturata",
        )
    )

    # 10. Avvertenza Sicurezza (5 pt) (usare solo in emergenza / assenza alimentazione)
    has_warning = (
        "emergenza" in output_text.lower()
        or "alimentazione" in output_text.lower()
        or "batteria" in output_text.lower()
        or "senza corrente" in output_text.lower()
        or "attenzione" in output_text.lower()
    )
    criteria.append(
        CriterionResult(
            id="safety_warning",
            name="Avvertenza di Sicurezza",
            category="data",
            points=5 if has_warning else 0,
            max_points=5,
            passed=has_warning,
            details="Specificato l'uso in assenza di alimentazione elettrica" if has_warning else "Nota di sicurezza non evidenziata",
        )
    )

    total_score = sum(c.points for c in criteria)
    rating, passed = _calc_rating(total_score)
    summary = f"{sum(1 for c in criteria if c.passed)}/10 criteri superati ({total_score}/100)"

    return EvaluationResult(
        test_id="test_2_pdf",
        score=total_score,
        max_score=100,
        rating=rating,
        passed=passed,
        summary=summary,
        criteria=criteria,
    )


def evaluate_word_test(
    test_result: Dict[str, Any], session_id: str, session_dir: Optional[Path]
) -> EvaluationResult:
    """Evaluates Test 3: Generazione Word Strutturato (100 pt)."""
    criteria: List[CriterionResult] = []
    output_text = test_result.get("final_output", "") + " " + test_result.get("reasoning", "")
    gen_files = test_result.get("generated_files", [])

    # Locate docx file in generated_files or session workspace
    docx_path: Optional[Path] = None
    for f in gen_files:
        if f.get("name", "").lower().endswith(".docx"):
            p = Path(f.get("abs_path", ""))
            if p.exists():
                docx_path = p
                break

    if not docx_path and session_dir and session_dir.exists():
        candidates = list(session_dir.rglob("*.docx"))
        if candidates:
            docx_path = candidates[0]

    docx_info = _inspect_docx(docx_path) if docx_path else {"valid": False}
    docx_text = docx_info.get("text_content", "")
    combined_text = docx_text + "\n" + output_text

    # 1. Esistenza File Word (15 pt)
    has_file = docx_path is not None and docx_path.exists()
    criteria.append(
        CriterionResult(
            id="file_created",
            name="Creazione File Word (agenda_kickoff.docx)",
            category="file",
            points=15 if has_file else 0,
            max_points=15,
            passed=has_file,
            details=f"File generato con successo: {docx_path.name if docx_path else 'agenda_kickoff.docx'}" if has_file else "File .docx non trovato nel workspace",
        )
    )

    # 2. Validità e Dimensione Formato Docx (10 pt)
    is_valid_docx = docx_info.get("valid", False) and docx_info.get("size_bytes", 0) >= 3000
    criteria.append(
        CriterionResult(
            id="file_validity",
            name="Integrità Struttura Docx (>3 KB)",
            category="file",
            points=10 if is_valid_docx else 0,
            max_points=10,
            passed=is_valid_docx,
            details=f"Documento XML Word valido ({docx_info.get('size_bytes', 0)} bytes)" if is_valid_docx else "Struttura docx invalida o file vuoto",
        )
    )

    # 3. Intestazione Ufficiale Kickoff (10 pt)
    has_heading = (
        "kickoff" in docx_text.lower()
        or "kick-off" in docx_text.lower()
        or "riunione aziendale" in docx_text.lower()
        or "ordine del giorno" in docx_text.lower()
    )
    criteria.append(
        CriterionResult(
            id="doc_heading",
            name="Intestazione Ufficiale Riunione",
            category="data",
            points=10 if has_heading else 0,
            max_points=10,
            passed=has_heading,
            details="Presenza di intestazione formattata per la riunione di Kickoff" if has_heading else "Intestazione Kickoff mancante nel documento",
        )
    )

    # 4. Data "15 Ottobre" (10 pt)
    has_date = (
        "15 ottobre" in docx_text.lower()
        or "15/10" in docx_text.lower()
        or "15 ott" in docx_text.lower()
        or "october 15" in docx_text.lower()
    )
    criteria.append(
        CriterionResult(
            id="meeting_date",
            name="Data Riunione (15 Ottobre)",
            category="data",
            points=10 if has_date else 0,
            max_points=10,
            passed=has_date,
            details="Data '15 Ottobre' presente nel documento Word" if has_date else "Data '15 Ottobre' non trovata nel docx",
        )
    )

    # 5. Presenza Tabella Strutturata (15 pt)
    has_table = docx_info.get("tables_count", 0) >= 1
    criteria.append(
        CriterionResult(
            id="table_present",
            name="Tabella Ordine del Giorno nel Docx",
            category="file",
            points=15 if has_table else 0,
            max_points=15,
            passed=has_table,
            details=f"Trovata tabella formattata con {docx_info.get('table_row_count', 0)} righe" if has_table else "Nessuna tabella trovata nel file docx",
        )
    )

    # 6. Colonna "Orario" (5 pt)
    table_headers_str = " ".join(docx_info.get("table_headers", [])).lower()
    has_col_time = "orario" in table_headers_str or "ora" in table_headers_str or "time" in table_headers_str or "slot" in table_headers_str
    criteria.append(
        CriterionResult(
            id="col_time",
            name="Colonna Tabella: 'Orario'",
            category="file",
            points=5 if has_col_time else 0,
            max_points=5,
            passed=has_col_time,
            details="Colonna 'Orario' presente nell'intestazione tabella" if has_col_time else "Colonna 'Orario' non rilevata",
        )
    )

    # 7. Colonna "Argomento" (5 pt)
    has_col_topic = "argomento" in table_headers_str or "tema" in table_headers_str or "topic" in table_headers_str or "descrizione" in table_headers_str or "attività" in table_headers_str
    criteria.append(
        CriterionResult(
            id="col_topic",
            name="Colonna Tabella: 'Argomento'",
            category="file",
            points=5 if has_col_topic else 0,
            max_points=5,
            passed=has_col_topic,
            details="Colonna 'Argomento' presente nell'intestazione tabella" if has_col_topic else "Colonna 'Argomento' non rilevata",
        )
    )

    # 8. Colonna "Relatore" (5 pt)
    has_col_speaker = "relatore" in table_headers_str or "speaker" in table_headers_str or "responsabile" in table_headers_str or "presenter" in table_headers_str or "referente" in table_headers_str
    criteria.append(
        CriterionResult(
            id="col_speaker",
            name="Colonna Tabella: 'Relatore'",
            category="file",
            points=5 if has_col_speaker else 0,
            max_points=5,
            passed=has_col_speaker,
            details="Colonna 'Relatore' presente nell'intestazione tabella" if has_col_speaker else "Colonna 'Relatore' non rilevata",
        )
    )

    # 9. Più Righe di Ordine del Giorno (10 pt)
    has_multiple_rows = docx_info.get("table_row_count", 0) >= 3
    criteria.append(
        CriterionResult(
            id="table_rows",
            name="Articolazione Agenda (>= 3 Slot Orari)",
            category="data",
            points=10 if has_multiple_rows else 0,
            max_points=10,
            passed=has_multiple_rows,
            details=f"Tabella compilata con {docx_info.get('table_row_count', 0)} righe di agenda" if has_multiple_rows else "Tabella incompleta (< 3 righe)",
        )
    )

    # 10. Elenco Materiali Preparatori (15 pt)
    has_materials = (
        ("material" in combined_text.lower() or "preparator" in combined_text.lower() or "richiest" in combined_text.lower() or "document" in combined_text.lower())
        and (len(docx_info.get("paragraphs", [])) >= 4 or "•" in combined_text or "-" in combined_text)
    )
    criteria.append(
        CriterionResult(
            id="preparatory_materials",
            name="Elenco Materiali Preparatori",
            category="data",
            points=15 if has_materials else 0,
            max_points=15,
            passed=has_materials,
            details="Sezione con elenco puntato dei materiali richiesti ai partecipanti" if has_materials else "Elenco materiali preparatori mancante o incompleto",
        )
    )

    total_score = sum(c.points for c in criteria)
    rating, passed = _calc_rating(total_score)
    summary = f"{sum(1 for c in criteria if c.passed)}/10 criteri superati ({total_score}/100)"

    return EvaluationResult(
        test_id="test_3_word",
        score=total_score,
        max_score=100,
        rating=rating,
        passed=passed,
        summary=summary,
        criteria=criteria,
    )


def evaluate_generic_test(test_result: Dict[str, Any]) -> EvaluationResult:
    """Fallback evaluator for custom/generic tests."""
    status = test_result.get("status")
    duration = test_result.get("duration_sec", 0)
    tools = test_result.get("tool_calls", [])
    output = test_result.get("final_output", "")

    criteria = [
        CriterionResult(
            id="completion",
            name="Completamento Senza Errori",
            category="tool",
            points=40 if status == "completed" else 0,
            max_points=40,
            passed=status == "completed",
            details="Test completato con successo" if status == "completed" else f"Errore: {test_result.get('error')}",
        ),
        CriterionResult(
            id="tool_usage",
            name="Utilizzo Strumenti",
            category="tool",
            points=30 if len(tools) > 0 else 0,
            max_points=30,
            passed=len(tools) > 0,
            details=f"Invocati {len(tools)} tool" if len(tools) > 0 else "Nessun tool invocato",
        ),
        CriterionResult(
            id="output_presence",
            name="Generazione Risposta",
            category="data",
            points=30 if len(output.strip()) > 50 else 0,
            max_points=30,
            passed=len(output.strip()) > 50,
            details="Risposta finale generata" if len(output.strip()) > 50 else "Risposta vuota",
        ),
    ]
    total_score = sum(c.points for c in criteria)
    rating, passed = _calc_rating(total_score)
    return EvaluationResult(
        test_id=test_result.get("id", "generic"),
        score=total_score,
        max_score=100,
        rating=rating,
        passed=passed,
        summary=f"{total_score}/100",
        criteria=criteria,
    )


def evaluate_test(
    test_id: str,
    test_result: Dict[str, Any],
    session_id: str = "",
    session_dir: Optional[Path] = None,
) -> EvaluationResult:
    """Main entry point to statically score any smoke test result."""
    if test_id == "test_1_excel":
        return evaluate_excel_test(test_result, session_id, session_dir)
    elif test_id == "test_2_pdf":
        return evaluate_pdf_test(test_result, session_id, session_dir)
    elif test_id == "test_3_word":
        return evaluate_word_test(test_result, session_id, session_dir)
    else:
        return evaluate_generic_test(test_result)
