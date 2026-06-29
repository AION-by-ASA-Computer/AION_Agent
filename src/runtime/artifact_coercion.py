"""Recover file artifacts from malformed markdown fences when the stream parser missed them."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.runtime.artifact_parser import _ARTIFACT_METADATA_LINE_RE, _sanitize_artifact_filename, _slug_artifact_id

_FENCE_RE = re.compile(r"```(?:markdown|md)?\s*\n([\s\S]*?)```+", re.IGNORECASE)
_MIN_SALVAGE_CHARS = 200


@dataclass
class SalvagedArtifact:
    artifact_id: str
    title: str
    filename: str
    artifact_type: str
    content: str


def _strip_metadata_prefix(body: str) -> str:
    lines: list[str] = []
    past_meta = False
    for line in body.splitlines():
        if not past_meta and _ARTIFACT_METADATA_LINE_RE.match(line):
            continue
        if not past_meta and not line.strip():
            continue
        past_meta = True
        lines.append(line)
    return "\n".join(lines).strip()


def salvage_artifact_from_response(text: str) -> Optional[SalvagedArtifact]:
    """Return the largest salvageable fenced block, or None."""
    if not text or len(text) < _MIN_SALVAGE_CHARS:
        return None

    best: Optional[SalvagedArtifact] = None
    for match in _FENCE_RE.finditer(text):
        body = match.group(1)
        if len(body) < _MIN_SALVAGE_CHARS:
            continue

        meta: dict[str, str] = {}
        for key, val in _ARTIFACT_METADATA_LINE_RE.findall(body[:4000]):
            k = key.lower()
            if k == "filename":
                meta[k] = _sanitize_artifact_filename(val.strip())
            elif k == "artifact_id":
                meta[k] = _slug_artifact_id(val.strip())
            else:
                meta[k] = val.strip()[:240]

        artifact_id = meta.get("artifact_id") or ""
        title = meta.get("title") or ""
        filename = meta.get("filename") or ""

        content = _strip_metadata_prefix(body)
        if not artifact_id and not filename:
            heading = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            if heading:
                title = heading.group(1).strip()[:120]
                artifact_id = _slug_artifact_id(title)
                filename = f"{artifact_id}.md"

        if not artifact_id and not filename:
            continue
        if not artifact_id:
            artifact_id = _slug_artifact_id(filename or title)
        if not filename:
            filename = f"{artifact_id}.md"
        if not title:
            title = artifact_id.replace("_", " ").title()

        if len(content) < _MIN_SALVAGE_CHARS - 50:
            continue

        candidate = SalvagedArtifact(
            artifact_id=artifact_id,
            title=title,
            filename=filename,
            artifact_type="markdown",
            content=content,
        )
        if best is None or len(candidate.content) > len(best.content):
            best = candidate
    return best
