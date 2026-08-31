"""Scoring helpers for long-document pipeline evals (ingest + grep, no LLM)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.tools.session_fs_tools import grep_content


def page_no_from_hit_file(file_path: str) -> int | None:
    """Extract page number from ``derived/docs/<slug>/pages/p0101.txt``."""
    name = Path(file_path.replace("\\", "/")).name
    m = re.match(r"^p(\d{4})\.txt$", name)
    return int(m.group(1)) if m else None


def grep_pages(
    session_root: Path,
    slug: str,
    pattern: str,
    *,
    max_matches: int = 500,
) -> list[dict]:
    return grep_content(
        session_root,
        session_root / "derived",
        pattern,
        glob_filter=f"docs/{slug}/pages/*.txt",
        max_matches=max_matches,
    )


def score_required_hits(
    session_root: Path,
    slug: str,
    required_hits: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score PIC/PMC-style expectations after ``doc_ingest``."""
    details: list[dict[str, Any]] = []
    passed = 0

    for item in required_hits:
        label = str(item.get("label") or item.get("id") or "hit")
        pattern = str(item["grep_pattern"])
        expected_page = item.get("page")
        must_contain = [str(s) for s in (item.get("must_contain") or [])]

        hits = grep_pages(session_root, slug, pattern)
        page_hits = [h for h in hits if page_no_from_hit_file(h["file"]) is not None]
        on_page = (
            [
                h
                for h in page_hits
                if page_no_from_hit_file(h["file"]) == int(expected_page)
            ]
            if expected_page is not None
            else page_hits
        )

        row: dict[str, Any] = {
            "label": label,
            "grep_pattern": pattern,
            "expected_page": expected_page,
            "hit_count": len(hits),
            "hits_on_expected_page": len(on_page),
            "passed": False,
            "reason": "",
        }

        if not hits:
            row["reason"] = "no grep hits"
            details.append(row)
            continue

        if expected_page is not None and not on_page:
            found_pages = sorted(
                {page_no_from_hit_file(h["file"]) for h in page_hits} - {None}
            )
            row["reason"] = f"hits on pages {found_pages}, expected {expected_page}"
            details.append(row)
            continue

        target_hit = on_page[0] if on_page else hits[0]
        page_no = page_no_from_hit_file(target_hit["file"])
        page_path = session_root / target_hit["file"]
        body = page_path.read_text(encoding="utf-8", errors="replace")
        missing = [s for s in must_contain if s not in body]
        if missing:
            row["reason"] = f"missing substrings on page {page_no}: {missing}"
            row["page"] = page_no
            details.append(row)
            continue

        row["passed"] = True
        row["page"] = page_no
        row["file"] = target_hit["file"]
        passed += 1
        details.append(row)

    total = len(required_hits)
    return {
        "required_total": total,
        "required_passed": passed,
        "recall": (passed / total) if total else 1.0,
        "details": details,
    }


def score_identity_gate(
    manifest: dict[str, Any], identity: dict[str, Any]
) -> dict[str, Any]:
    """Check title/excerpt against must / must-not lists."""
    haystack = " ".join(
        [
            str(manifest.get("title_guess") or ""),
            str(manifest.get("first_page_excerpt") or ""),
            str(manifest.get("source") or ""),
        ]
    ).lower()

    must = [str(s).lower() for s in (identity.get("must_contain") or [])]
    must_not = [str(s).lower() for s in (identity.get("must_not_contain") or [])]

    missing = [s for s in must if s not in haystack]
    forbidden = [s for s in must_not if s in haystack]
    passed = not missing and not forbidden
    return {
        "passed": passed,
        "missing": missing,
        "forbidden": forbidden,
    }


def score_agent_output(text: str, expectations: dict[str, Any]) -> dict[str, Any]:
    """Lightweight substring checks on a final agent answer (opt-in LLM eval)."""
    low = (text or "").lower()
    must = [str(s) for s in (expectations.get("output_must_contain") or [])]
    must_not = [str(s) for s in (expectations.get("output_must_not_contain") or [])]

    missing = [s for s in must if s.lower() not in low]
    forbidden = [s for s in must_not if s.lower() in low]
    passed = not missing and not forbidden
    return {
        "passed": passed,
        "missing": missing,
        "forbidden": forbidden,
    }
