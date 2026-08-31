"""Synthetic PDF fixtures for long-document eval cases (no external assets)."""

from __future__ import annotations

from pathlib import Path

_FILLER = (
    "Commissione Istruttoria IPPC - Centrale termoelettrica - testo di riempimento "
    "per riprodurre la densita tipica di una pagina di decreto autorizzativo."
)


def build_rumore_decreto_pdf(
    path: Path,
    *,
    pages: int = 200,
    prescription_page: int = 101,
    pmc_page: int = 150,
    blank_pages: frozenset[int] | None = None,
) -> Path:
    """Born-digital decree-like PDF with PIC + PMC noise markers on known pages."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    blanks = blank_pages if blank_pages is not None else frozenset({7, 42})
    path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(path), pagesize=A4)
    for page_no in range(1, pages + 1):
        if page_no not in blanks:
            c.drawString(72, 780, f"PAGINA {page_no} marcatore acustico")
            for row, offset in enumerate(range(750, 690, -15)):
                c.drawString(72, offset, f"{_FILLER} riga {row}")
            if page_no == prescription_page:
                c.drawString(
                    72,
                    660,
                    "[53] Il Gestore e tenuto al rispetto dei valori limite di rumore",
                )
                c.drawString(72, 645, "8.9 Rumore - Parere Istruttorio Conclusivo")
            if page_no == pmc_page:
                c.drawString(72, 660, "Piano di Monitoraggio e Controllo (PMC)")
                c.drawString(
                    72, 645, "Tabella parametri Rumore e monitoraggio acustico"
                )
        c.showPage()
    c.save()
    return path
