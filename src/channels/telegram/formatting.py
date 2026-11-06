"""Markdown dell'agente → HTML di Telegram, e suddivisione in messaggi da 4096.

Telegram accetta solo un sottoinsieme di HTML (b, i, s, u, code, pre, a,
blockquote) e rifiuta il messaggio se i tag non sono bilanciati. Per questo:
- si esegue l'escape di tutto il testo e si ricostruiscono solo i tag ammessi;
- la suddivisione avviene sul Markdown, per righe, richiudendo e riaprendo i
  blocchi di codice spezzati, così ogni parte è HTML valido da sola.
Se Telegram rifiuta comunque l'HTML, chi invia ripiega sul testo semplice.
"""

from __future__ import annotations

import re
from html import escape
from typing import List

TELEGRAM_LIMIT = 4096
# Margine per i tag aggiunti dalla conversione (il limite vale dopo il parsing).
_CHUNK_MD = 3500

_FENCE_RE = re.compile(r"^\s*```(.*)$")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__")
_ITALIC_RE = re.compile(
    r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])|(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])"
)
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_HR_RE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _inline(text: str) -> str:
    """Formattazione in linea su testo già senza codice."""
    placeholders: List[str] = []

    def stash(html: str) -> str:
        placeholders.append(html)
        return f"\x00{len(placeholders) - 1}\x00"

    # Codice e link prima: il loro contenuto non va reinterpretato.
    text = _INLINE_CODE_RE.sub(
        lambda m: stash(f"<code>{escape(m.group(1))}</code>"), text
    )
    text = _LINK_RE.sub(
        lambda m: stash(
            f'<a href="{escape(m.group(2), quote=True)}">{escape(m.group(1))}</a>'
        ),
        text,
    )
    text = escape(text, quote=False)
    text = _BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _STRIKE_RE.sub(lambda m: f"<s>{m.group(1)}</s>", text)
    text = _ITALIC_RE.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], text)


def markdown_to_html(md: str) -> str:
    out: List[str] = []
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    quote: List[str] = []

    def flush_quote() -> None:
        if quote:
            out.append("<blockquote>" + "\n".join(quote) + "</blockquote>")
            quote.clear()

    while i < len(lines):
        line = lines[i]
        fence = _FENCE_RE.match(line)
        if fence:
            flush_quote()
            lang = fence.group(1).strip().split(" ")[0]
            body: List[str] = []
            i += 1
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # chiusura (o fine testo: blocco non chiuso durante lo streaming)
            code = escape("\n".join(body))
            cls = f' class="language-{escape(lang, quote=True)}"' if lang else ""
            out.append(f"<pre><code{cls}>{code}</code></pre>")
            continue
        # Tabelle Markdown: Telegram non le supporta, restano allineate in <pre>.
        if (
            line.lstrip().startswith("|")
            and i + 1 < len(lines)
            and _TABLE_SEP_RE.match(lines[i + 1])
        ):
            flush_quote()
            rows: List[str] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                if not _TABLE_SEP_RE.match(lines[i]):
                    rows.append(lines[i].strip())
                i += 1
            out.append("<pre>" + escape("\n".join(rows)) + "</pre>")
            continue
        if line.lstrip().startswith(">"):
            quote.append(_inline(line.lstrip()[1:].lstrip()))
            i += 1
            continue
        flush_quote()
        heading = _HEADING_RE.match(line)
        bullet = _BULLET_RE.match(line)
        if heading:
            out.append(f"<b>{_inline(heading.group(1))}</b>")
        elif _HR_RE.match(line):
            out.append("──────────")
        elif bullet:
            indent = "  " * (len(bullet.group(1).expandtabs(2)) // 2)
            out.append(f"{indent}• {_inline(bullet.group(2))}")
        else:
            out.append(_inline(line))
        i += 1
    flush_quote()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def split_markdown(md: str, limit: int = _CHUNK_MD) -> List[str]:
    """Divide per righe; un blocco di codice spezzato viene chiuso e riaperto."""
    md = md.replace("\r\n", "\n").strip()
    if len(md) <= limit:
        return [md] if md else []
    chunks: List[str] = []
    current: List[str] = []
    size = 0
    open_fence: str | None = None

    def flush() -> None:
        nonlocal current, size
        if not current:
            return
        text = "\n".join(current)
        if open_fence is not None:
            text += "\n```"
        chunks.append(text)
        current = [f"```{open_fence}"] if open_fence is not None else []
        size = sum(len(x) + 1 for x in current)

    for raw in md.split("\n"):
        # Righe più lunghe del limite: spezzate a forza.
        pieces = [raw[k : k + limit] for k in range(0, len(raw), limit)] or [""]
        for line in pieces:
            if size + len(line) + 1 > limit and current:
                flush()
            current.append(line)
            size += len(line) + 1
            fence = _FENCE_RE.match(line)
            if fence:
                open_fence = None if open_fence is not None else fence.group(1).strip()
    if current:
        text = "\n".join(current)
        chunks.append(text)
    return [c for c in (c.strip() for c in chunks) if c and c != "```"]


def preview_markdown(md: str, limit: int = _CHUNK_MD) -> str:
    """Coda del testo in corso di generazione, entro il limite di un messaggio."""
    md = md.strip()
    if len(md) <= limit:
        return md
    tail = md[-limit:]
    cut = tail.find("\n")
    tail = tail[cut + 1 :] if 0 <= cut < 400 else tail
    # Se la coda inizia dentro un blocco di codice, lo riapre.
    if md[: len(md) - len(tail)].count("```") % 2 == 1:
        tail = "```\n" + tail
    return "…\n" + tail


def strip_html(html: str) -> str:
    """Testo semplice per il fallback quando Telegram rifiuta l'HTML."""
    from html import unescape

    return unescape(re.sub(r"<[^>]+>", "", html))
