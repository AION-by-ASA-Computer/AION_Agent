"""Template email (``templates/<lang>/<kind>.txt|.html``).

Il file ``.txt`` ha l'oggetto sulla prima riga, una riga vuota e poi il corpo.
Le variabili usano la sintassi ``string.Template`` (``$link``, ``${name}``);
nell'HTML i valori sono sottoposti a escape.
"""

from __future__ import annotations

import html
from pathlib import Path
from string import Template
from typing import Dict, Tuple

from .smtp_settings import EMAIL_LANGUAGES

_DIR = Path(__file__).resolve().parent / "templates"

KINDS = ("invite", "reset", "migration", "test")


def render(kind: str, lang: str, values: Dict[str, str]) -> Tuple[str, str, str]:
    """Ritorna ``(subject, text, html)``."""
    if kind not in KINDS:
        raise ValueError(f"unknown template: {kind}")
    lang = lang if lang in EMAIL_LANGUAGES else "it"
    raw = (_DIR / lang / f"{kind}.txt").read_text(encoding="utf-8")
    subject_tpl, _, body_tpl = raw.partition("\n\n")
    subject = Template(subject_tpl.strip()).safe_substitute(values)
    text = Template(body_tpl).safe_substitute(values)
    escaped = {k: html.escape(v, quote=True) for k, v in values.items()}
    html_tpl = (_DIR / lang / f"{kind}.html").read_text(encoding="utf-8")
    body_html = Template(html_tpl).safe_substitute(escaped)
    layout = (_DIR / "layout.html").read_text(encoding="utf-8")
    page = Template(layout).safe_substitute(
        subject=html.escape(subject),
        body=body_html,
        platform=escaped.get("platform", ""),
    )
    return subject, text, page
