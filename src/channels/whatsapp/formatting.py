"""Conversione Markdown → formattazione WhatsApp e split in messaggi ≤ 4096.

WhatsApp supporta ``*grassetto*``, ``_corsivo_``, ``~barrato~``, ```` ``` ````
monospace, `` `codice` `` inline, ``> citazione`` ed elenchi; niente titoli,
link Markdown né tabelle, che convertiamo in testo leggibile.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional

MAX_MESSAGE_CHARS = 4096
DEFAULT_MAX_CHUNKS = 3

_FENCE_RE = re.compile(r"(```.*?```)", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"(`[^`\n]+`)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_BOLD_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"(?<![*\w])\*(?=[^\s*])([^*\n]+?)(?<=\S)\*(?![*\w])")
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+", re.MULTILINE)
_HR_RE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$", re.MULTILINE)
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")

_BOLD_MARK = "\x01"


def max_chunks_from_env() -> int:
    try:
        return max(1, int(os.getenv("AION_WHATSAPP_MAX_CHUNKS") or DEFAULT_MAX_CHUNKS))
    except ValueError:
        return DEFAULT_MAX_CHUNKS


def _table_cells(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _convert_tables(text: str) -> str:
    lines = text.split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if "|" in line and _TABLE_SEP_RE.match(nxt or ""):
            header = _table_cells(line)
            out.append(_BOLD_MARK + " — ".join(h for h in header if h) + _BOLD_MARK)
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                cells = [c for c in _table_cells(lines[i]) if c]
                out.append("• " + " — ".join(cells))
                i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _link(m: re.Match) -> str:
    label, url = m.group(1).strip(), m.group(2).strip()
    if not label or label == url:
        return url
    return f"{label} ({url})"


def _convert_prose(text: str) -> str:
    # Il codice inline resta com'è: lo isoliamo dalle altre sostituzioni.
    parts = _INLINE_CODE_RE.split(text)
    for idx in range(0, len(parts), 2):
        p = parts[idx]
        p = _convert_tables(p)
        p = _HR_RE.sub("", p)
        p = _HEADING_RE.sub(lambda m: f"{_BOLD_MARK}{m.group(1)}{_BOLD_MARK}", p)
        p = _IMAGE_RE.sub(
            lambda m: (
                f"{m.group(1).strip()}: {m.group(2)}"
                if m.group(1).strip()
                else m.group(2)
            ),
            p,
        )
        p = _LINK_RE.sub(_link, p)
        p = _BULLET_RE.sub(lambda m: f"{m.group(1)}• ", p)
        p = _BOLD_RE.sub(lambda m: f"{_BOLD_MARK}{m.group(2)}{_BOLD_MARK}", p)
        p = _ITALIC_STAR_RE.sub(r"_\1_", p)
        p = _STRIKE_RE.sub(r"~\1~", p)
        parts[idx] = p.replace(_BOLD_MARK, "*")
    return "".join(parts)


def markdown_to_whatsapp(text: str) -> str:
    if not text:
        return ""
    chunks = _FENCE_RE.split(text.replace("\r\n", "\n"))
    out: List[str] = []
    for idx, chunk in enumerate(chunks):
        if idx % 2 == 1:
            # Blocco di codice: WhatsApp non ha il tag linguaggio dopo ```.
            out.append(re.sub(r"^```[\w+-]+\n", "```\n", chunk))
        else:
            out.append(_convert_prose(chunk))
    result = "".join(out)
    return re.sub(r"\n{3,}", "\n\n", result).strip()


def _hard_split(piece: str, limit: int) -> List[str]:
    return [piece[i : i + limit] for i in range(0, len(piece), limit)]


def split_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> List[str]:
    """Spezza su paragrafo, poi su riga, poi a taglio netto."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
            continue
        flush()
        if len(para) <= limit:
            current = para
            continue
        for line in para.split("\n"):
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) <= limit:
                current = candidate
                continue
            flush()
            if len(line) <= limit:
                current = line
            else:
                pieces = _hard_split(line, limit)
                chunks.extend(pieces[:-1])
                current = pieces[-1]
    flush()
    return chunks


def prepare_reply(
    markdown: str,
    *,
    continue_url: Optional[str] = None,
    max_chunks: Optional[int] = None,
    limit: int = MAX_MESSAGE_CHARS,
    continue_label: str = "Continua su AION",
) -> List[str]:
    """Testo finale dell'agente → messaggi WhatsApp pronti da inviare.

    Oltre ``max_chunks`` messaggi la risposta viene troncata e l'ultimo
    messaggio termina con il link alla conversazione nella chat-ui.
    """
    max_chunks = max_chunks or max_chunks_from_env()
    chunks = split_message(markdown_to_whatsapp(markdown), limit)
    if len(chunks) <= max_chunks:
        return chunks
    suffix = f"\n\n… {continue_label}: {continue_url}" if continue_url else "\n\n…"
    kept = chunks[:max_chunks]
    last = kept[-1]
    room = limit - len(suffix)
    if len(last) > room:
        cut = last[:room]
        # Taglia sull'ultimo spazio per non spezzare una parola.
        space = cut.rfind(" ")
        last = cut[:space] if space > room // 2 else cut
    kept[-1] = last.rstrip() + suffix
    return kept
