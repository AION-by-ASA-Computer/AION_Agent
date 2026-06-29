import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ArtifactEvent(Enum):
    TEXT = "text"
    ARTIFACT_START = "artifact_start"
    ARTIFACT_CONTENT = "artifact_content"
    ARTIFACT_END = "artifact_end"


@dataclass
class ParsedEvent:
    event: ArtifactEvent
    content: str = ""
    artifact_id: Optional[str] = None
    artifact_type: Optional[str] = None
    artifact_title: Optional[str] = None
    auto_execute: bool = False
    filename: Optional[str] = None


class BaseArtifactStreamParser:
    """Base class for all artifact stream parsers."""

    def feed(self, token: str) -> list[ParsedEvent]:
        raise NotImplementedError

    def flush(self) -> list[ParsedEvent]:
        raise NotImplementedError


class XMLArtifactStreamParser(BaseArtifactStreamParser):
    """
    State machine that processes tokens in streaming and separates normal text from <aion_artifact> blocks.
    """

    OPEN_TAG_START = "<aion_artifact"
    CLOSE_TAG = "</aion_artifact>"

    # Permissive attribute regex: matches key="value", key='value', or key=value (no spaces in value)
    _ATTR_RE = re.compile(r'(\w+)\s*=\s*(?:["\']([^"\']*)["\']|([^\s>]+))')

    def __init__(self):
        self._state = "NORMAL"
        self._buffer = ""
        self._tag_buffer = ""
        self._content_buffer = ""
        self._current_attrs: dict = {}
        self._active_open_tag = ""
        self._active_close_tag = ""
        self.TAGS = {"<aion_artifact": "</aion_artifact>", "<plan": "</plan>"}

    def feed(self, token: str) -> list[ParsedEvent]:
        """Feed a token, return a list of events."""
        self._buffer += token
        return self._process()

    def flush(self) -> list[ParsedEvent]:
        """Flush residual buffer (end of stream)."""
        events = []
        if self._state == "NORMAL" and self._buffer:
            events.append(ParsedEvent(ArtifactEvent.TEXT, content=self._buffer))
            self._buffer = ""
        elif self._state == "CONTENT" and (self._content_buffer or self._buffer):
            # Cut off mid-artifact: emit what we have as a finalized artifact
            if self._buffer:
                self._content_buffer += self._buffer
                events.append(
                    ParsedEvent(ArtifactEvent.ARTIFACT_CONTENT, content=self._buffer)
                )

            events.append(
                ParsedEvent(
                    ArtifactEvent.ARTIFACT_END,
                    content=self._content_buffer,
                    artifact_id=self._current_attrs.get("identifier"),
                    artifact_type=self._current_attrs.get("type", "text"),
                    artifact_title=self._current_attrs.get("title"),
                    filename=self._current_attrs.get("filename"),
                )
            )
            self._reset()
        elif self._state == "TAG_OPEN":
            # Tag never finished: emit as text
            events.append(
                ParsedEvent(ArtifactEvent.TEXT, content=self._tag_buffer + self._buffer)
            )
            self._reset()
        return events

    def _reset(self):
        self._state = "NORMAL"
        self._buffer = ""
        self._tag_buffer = ""
        self._content_buffer = ""
        self._current_attrs = {}

    def _process(self) -> list[ParsedEvent]:
        events = []
        while self._buffer:
            if self._state == "NORMAL":
                matched_tag = None
                matched_idx = -1
                for open_tag in self.TAGS:
                    idx = self._buffer.find(open_tag)
                    if idx != -1:
                        if matched_idx == -1 or idx < matched_idx:
                            matched_idx = idx
                            matched_tag = open_tag

                if matched_tag:
                    if matched_idx > 0:
                        events.append(
                            ParsedEvent(
                                ArtifactEvent.TEXT, content=self._buffer[:matched_idx]
                            )
                        )

                    self._tag_buffer = matched_tag
                    self._active_open_tag = matched_tag
                    self._active_close_tag = self.TAGS[matched_tag]
                    self._buffer = self._buffer[matched_idx + len(matched_tag) :]
                    self._state = "TAG_OPEN"
                else:
                    # Potential partial match at the end of buffer
                    partial = False
                    for open_tag in self.TAGS:
                        for i in range(1, len(open_tag)):
                            if self._buffer.endswith(open_tag[:i]):
                                partial = True
                                idx = len(self._buffer) - i
                                if idx > 0:
                                    events.append(
                                        ParsedEvent(
                                            ArtifactEvent.TEXT,
                                            content=self._buffer[:idx],
                                        )
                                    )
                                    self._buffer = self._buffer[idx:]
                                break
                        if partial:
                            break

                    if not partial:
                        events.append(
                            ParsedEvent(ArtifactEvent.TEXT, content=self._buffer)
                        )
                        self._buffer = ""
                    else:
                        break

            elif self._state == "TAG_OPEN":
                if ">" in self._buffer:
                    idx = self._buffer.find(">")
                    self._tag_buffer += self._buffer[: idx + 1]
                    self._buffer = self._buffer[idx + 1 :]

                    attrs = self._parse_tag_attrs(self._tag_buffer)
                    if self._active_open_tag == "<plan":
                        attrs["type"] = "plan"
                        if "identifier" not in attrs:
                            import uuid

                            attrs["identifier"] = "execution_plan_" + str(
                                uuid.uuid4().hex[:6]
                            )

                    self._current_attrs = attrs

                    events.append(
                        ParsedEvent(
                            ArtifactEvent.ARTIFACT_START,
                            artifact_id=attrs.get("identifier"),
                            artifact_type=attrs.get("type", "text"),
                            artifact_title=attrs.get("title") or "Execution Plan"
                            if attrs.get("type") == "plan"
                            else attrs.get("title"),
                            auto_execute=attrs.get("auto_execute", "false").lower()
                            in ("true", "1", "yes"),
                            filename=attrs.get("filename"),
                        )
                    )
                    self._state = "CONTENT"
                    self._content_buffer = ""
                else:
                    self._tag_buffer += self._buffer
                    self._buffer = ""

            elif self._state == "CONTENT":
                if self._active_close_tag in self._buffer:
                    idx = self._buffer.find(self._active_close_tag)
                    content_chunk = self._buffer[:idx]
                    if content_chunk:
                        self._content_buffer += content_chunk
                        events.append(
                            ParsedEvent(
                                ArtifactEvent.ARTIFACT_CONTENT, content=content_chunk
                            )
                        )

                    self._buffer = self._buffer[idx + len(self._active_close_tag) :]

                    events.append(
                        ParsedEvent(
                            ArtifactEvent.ARTIFACT_END,
                            content=self._content_buffer,
                            artifact_id=self._current_attrs.get("identifier"),
                            artifact_type=self._current_attrs.get("type", "text"),
                            artifact_title=self._current_attrs.get("title")
                            or "Execution Plan"
                            if self._current_attrs.get("type") == "plan"
                            else self._current_attrs.get("title"),
                            filename=self._current_attrs.get("filename"),
                        )
                    )
                    self._reset()
                else:
                    # Potential partial match for close tag
                    partial = False
                    for i in range(1, len(self._active_close_tag)):
                        if self._buffer.endswith(self._active_close_tag[:i]):
                            partial = True
                            idx = len(self._buffer) - i
                            content_chunk = self._buffer[:idx]
                            if content_chunk:
                                self._content_buffer += content_chunk
                                events.append(
                                    ParsedEvent(
                                        ArtifactEvent.ARTIFACT_CONTENT,
                                        content=content_chunk,
                                    )
                                )
                            self._buffer = self._buffer[idx:]
                            break

                    if not partial:
                        self._content_buffer += self._buffer
                        events.append(
                            ParsedEvent(
                                ArtifactEvent.ARTIFACT_CONTENT, content=self._buffer
                            )
                        )
                        self._buffer = ""
                    else:
                        break
        return events

    def _parse_tag_attrs(self, tag: str) -> dict:
        attrs = {}
        for match in self._ATTR_RE.finditer(tag):
            key = match.group(1)
            val = match.group(2) or match.group(3)
            attrs[key] = val
        return attrs


_ARTIFACT_METADATA_LINE_RE = re.compile(
    r"^\s*#?\s*(artifact_id|title|filename|auto_execute)\s*:\s*(.*)",
    re.IGNORECASE | re.MULTILINE,
)


def _sanitize_artifact_filename(value: str) -> str:
    v = (value or "").strip()
    v = re.sub(r"`+$", "", v)
    if not v:
        return ""
    base = v.split()[0] if "`" in v else v
    base = base.strip("`")
    return base[:240]


def _slug_artifact_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", (value or "").lower()).strip("_")
    return slug[:80] or "recovered_artifact"


class MarkdownArtifactStreamParser(BaseArtifactStreamParser):
    """
    Parser that detects standard Markdown code blocks and treats them as artifacts
     if they contain specific metadata in the first few lines.
     Format:
     ```python
     # artifact_id: my_script
     # title: My Script Title
     # filename: script.py
     print("hello")
     ```
    """

    def __init__(self):
        self._state = "NORMAL"
        self._buffer = ""
        self._content_buffer = ""
        self._metadata = {}
        self._block_started = False

    def feed(self, token: str) -> list[ParsedEvent]:
        self._buffer += token
        return self._process()

    def flush(self) -> list[ParsedEvent]:
        events = []
        if self._state == "NORMAL" and self._buffer:
            events.append(ParsedEvent(ArtifactEvent.TEXT, content=self._buffer))
        elif self._state == "CODE_BLOCK":
            # If stream ends inside a block, we close it as an artifact if we had metadata
            if self._block_started:
                events.append(
                    ParsedEvent(
                        ArtifactEvent.ARTIFACT_END,
                        content=self._content_buffer,
                        artifact_id=self._metadata.get("artifact_id"),
                        artifact_type=self._metadata.get("type", "text"),
                        artifact_title=self._metadata.get("title"),
                        filename=self._metadata.get("filename"),
                    )
                )
            elif self._metadata.get("artifact_id"):
                # Metadata was collected but ARTIFACT_START never emitted (all lines were metadata)
                events.append(
                    ParsedEvent(
                        ArtifactEvent.ARTIFACT_START,
                        artifact_id=self._metadata.get("artifact_id"),
                        artifact_type=self._metadata.get("type", "text"),
                        artifact_title=self._metadata.get("title"),
                        auto_execute=self._metadata.get("auto_execute", "false").lower()
                        in ("true", "1", "yes"),
                        filename=self._metadata.get("filename"),
                    )
                )
                events.append(
                    ParsedEvent(
                        ArtifactEvent.ARTIFACT_END,
                        content=self._content_buffer,
                        artifact_id=self._metadata.get("artifact_id"),
                        artifact_type=self._metadata.get("type", "text"),
                        artifact_title=self._metadata.get("title"),
                        filename=self._metadata.get("filename"),
                    )
                )
        return events

    def _process(self) -> list[ParsedEvent]:
        events = []
        while self._buffer:
            if self._state == "NORMAL":
                if "```" in self._buffer:
                    idx = self._buffer.find("```")
                    if idx > 0:
                        events.append(
                            ParsedEvent(ArtifactEvent.TEXT, content=self._buffer[:idx])
                        )

                    self._buffer = self._buffer[idx + 3 :]
                    self._state = "CODE_HEADER"
                    self._content_buffer = ""
                    self._metadata = {}
                    self._block_started = False
                else:
                    # Partial match wait
                    if self._buffer.endswith("`") or self._buffer.endswith("``"):
                        break
                    events.append(ParsedEvent(ArtifactEvent.TEXT, content=self._buffer))
                    self._buffer = ""

            elif self._state == "CODE_HEADER":
                # Look for the end of the line after ``` (the language)
                if "\n" in self._buffer:
                    idx = self._buffer.find("\n")
                    self._metadata["type"] = self._buffer[:idx].strip() or "text"
                    self._buffer = self._buffer[idx + 1 :]
                    self._state = "CODE_BLOCK"
                elif len(self._buffer) > 50:  # safety break if no newline
                    self._metadata["type"] = self._buffer.strip() or "text"
                    self._state = "CODE_BLOCK"
                    self._buffer = ""
                else:
                    break

            elif self._state == "CODE_BLOCK":
                if "```" in self._buffer:
                    idx = self._buffer.find("```")
                    chunk = self._buffer[:idx]
                    self._process_content(chunk, events)
                    self._buffer = self._buffer[idx + 3 :]

                    if self._block_started:
                        events.append(
                            ParsedEvent(
                                ArtifactEvent.ARTIFACT_END,
                                content=self._content_buffer,
                                artifact_id=self._metadata.get("artifact_id"),
                                artifact_type=self._metadata.get("type", "text"),
                                artifact_title=self._metadata.get("title"),
                                filename=self._metadata.get("filename"),
                            )
                        )
                    else:
                        # It was a normal code block, emit as text
                        # (actually we should have emitted it as we went, but for simplicity
                        # if it's not an artifact we just emit the whole block as text now)
                        events.append(
                            ParsedEvent(
                                ArtifactEvent.TEXT,
                                content="```" + self._content_buffer + "```",
                            )
                        )

                    self._state = "NORMAL"
                    self._content_buffer = ""
                    self._metadata = {}
                else:
                    # Collect content and check for metadata if not yet started
                    # Wait for newline to check metadata line by line
                    if "\n" in self._buffer:
                        idx = self._buffer.rfind("\n")
                        chunk = self._buffer[: idx + 1]
                        self._process_content(chunk, events)
                        self._buffer = self._buffer[idx + 1 :]
                    else:
                        # If buffer is getting large without newline, just process it
                        if len(self._buffer) > 500:
                            self._process_content(self._buffer, events)
                            self._buffer = ""
                        break
        return events

    def _infer_html_artifact_metadata_if_needed(self, line: str) -> bool:
        """Recover when the model emits ```html without # artifact_id metadata."""
        if self._metadata.get("artifact_id"):
            return True
        block_type = (self._metadata.get("type") or "").strip().lower()
        if block_type not in ("html", "htm"):
            return False
        stripped = line.strip()
        if not re.match(r"<!DOCTYPE\s+html|<html\b", stripped, re.I):
            return False
        self._metadata.setdefault("artifact_id", "inferred_html_page")
        self._metadata.setdefault("title", "HTML page")
        self._metadata.setdefault("filename", "page.html")
        return True

    def _infer_markdown_artifact_metadata_if_needed(self, line: str) -> bool:
        """Recover when the model emits ```markdown without # artifact_id metadata."""
        if self._metadata.get("artifact_id"):
            return True
        block_type = (self._metadata.get("type") or "").strip().lower()
        if block_type not in ("markdown", "md"):
            return False
        stripped = line.strip()
        if not stripped.startswith("#"):
            return False
        title = stripped.lstrip("#").strip()[:120]
        if len(title) < 3:
            return False
        slug = _slug_artifact_id(title)
        self._metadata.setdefault("artifact_id", slug)
        self._metadata.setdefault("title", title)
        self._metadata.setdefault("filename", f"{slug}.md")
        return True

    def _apply_metadata_line(self, key: str, val: str) -> None:
        if key == "filename":
            val = _sanitize_artifact_filename(val)
        elif key == "artifact_id":
            val = _slug_artifact_id(val) if val else val
        self._metadata[key] = val

    def _process_content(self, chunk: str, events: list[ParsedEvent]):
        if not self._block_started:
            # Try to find metadata in the lines
            # We must be careful to preserve the original chunk's newlines
            lines = chunk.splitlines(keepends=True)
            remaining_text = []
            found_artifact_id = bool(self._metadata.get("artifact_id"))

            for line in lines:
                if not self._block_started:
                    # Only check for metadata at the start of the block
                    m = _ARTIFACT_METADATA_LINE_RE.match(line)
                    if m:
                        key, val = m.group(1).lower(), m.group(2).strip()
                        self._apply_metadata_line(key, val)
                        if key == "artifact_id":
                            found_artifact_id = True
                        continue

                    # If we find a non-metadata, non-empty line
                    if line.strip():
                        if (
                            not found_artifact_id
                            and self._infer_html_artifact_metadata_if_needed(line)
                        ):
                            found_artifact_id = True
                        if (
                            not found_artifact_id
                            and self._infer_markdown_artifact_metadata_if_needed(line)
                        ):
                            found_artifact_id = True
                        if found_artifact_id:
                            # It's an artifact! Start it now.
                            self._block_started = True
                            events.append(
                                ParsedEvent(
                                    ArtifactEvent.ARTIFACT_START,
                                    artifact_id=self._metadata.get("artifact_id"),
                                    artifact_type=self._metadata.get("type", "text"),
                                    artifact_title=self._metadata.get("title"),
                                    auto_execute=self._metadata.get(
                                        "auto_execute", "false"
                                    ).lower()
                                    in ("true", "1", "yes"),
                                    filename=self._metadata.get("filename"),
                                )
                            )
                            remaining_text.append(line)
                        else:
                            # Not an artifact block (no artifact_id found before first content)
                            # We don't set self._block_started here, we just continue as TEXT
                            remaining_text.append(line)
                    else:
                        # Empty line: if we found an artifact_id, we keep it as part of the artifact
                        # if we haven't, it might be just leading whitespace in a normal block
                        remaining_text.append(line)
                else:
                    remaining_text.append(line)

            text_to_add = "".join(remaining_text)
            if self._block_started:
                if text_to_add:
                    self._content_buffer += text_to_add
                    events.append(
                        ParsedEvent(ArtifactEvent.ARTIFACT_CONTENT, content=text_to_add)
                    )
            else:
                self._content_buffer += text_to_add
        else:
            self._content_buffer += chunk
            events.append(ParsedEvent(ArtifactEvent.ARTIFACT_CONTENT, content=chunk))


class NoOpArtifactParser(BaseArtifactStreamParser):
    """Parser that does nothing, treating all input as plain text."""

    def feed(self, token: str) -> list[ParsedEvent]:
        return [ParsedEvent(ArtifactEvent.TEXT, content=token)]

    def flush(self) -> list[ParsedEvent]:
        return []


class PlanTagInterceptorParser(BaseArtifactStreamParser):
    """
    Wrapper parser that preserves inner artifact behavior and additionally
    intercepts raw `<plan>...</plan>` blocks from plain text events.
    """

    _OPEN = "<plan"
    _CLOSE = "</plan>"
    _ATTR_RE = re.compile(r'(\w+)\s*=\s*(?:["\']([^"\']*)["\']|([^\s>]+))')
    _PSEUDO_OPEN_RE = re.compile(r"(?:^|\n)(\s*)plan(\s+title\s*=)", re.IGNORECASE)
    _PSEUDO_OPEN_FIND_RE = re.compile(r"(?:^|\n)\s*plan\s+title\s*=", re.IGNORECASE)
    _PARTIAL_OPEN_MARKERS = (
        "<plan title=",
        "<plan title",
        "<plan titl",
        "<plan tit",
        "<plan ti",
        "<plan t",
        "<plan ",
        "<plan",
        "plan title=",
        "plan title",
        "plan titl",
        "plan tit",
        "plan ti",
        "plan t",
        "plan ",
        "plan",
    )

    def __init__(self, inner: BaseArtifactStreamParser):
        self._inner = inner
        self._state = "NORMAL"
        self._buffer = ""
        self._tag_buffer = ""
        self._current_attrs: dict = {}
        self._content_buffer = ""

    def is_suppressing_tokens(self) -> bool:
        """True while buffering plan markup that must not be forwarded as raw SSE tokens."""
        if self._state in ("OPEN_TAG", "CONTENT"):
            return True
        return bool(self._buffer)

    def feed(self, token: str) -> list[ParsedEvent]:
        inner_events = self._inner.feed(token)
        return self._rewrite(inner_events)

    def flush(self) -> list[ParsedEvent]:
        out = self._rewrite(self._inner.flush())
        out.extend(self._flush_self())
        return out

    def _rewrite(self, events: list[ParsedEvent]) -> list[ParsedEvent]:
        out: list[ParsedEvent] = []
        for ev in events:
            if ev.event != ArtifactEvent.TEXT:
                out.append(ev)
                continue
            out.extend(self._feed_text(ev.content))
        return out

    def _normalize_plan_openers(self, text: str) -> str:
        normalized = (
            (text or "")
            .replace("&lt;plan", "<plan")
            .replace("&lt;/plan&gt;", "</plan>")
            .replace("&gt;", ">")
        )
        normalized = self._PSEUDO_OPEN_RE.sub(r"\1<plan\2", normalized, count=1)
        # Models often omit `>` after title="..." before the markdown body.
        normalized = re.sub(
            r'(<plan\b[^>]*title\s*=\s*"[^"]*")\s*\n',
            r"\1>\n",
            normalized,
            count=1,
            flags=re.IGNORECASE,
        )
        return normalized

    def _find_open_index(self, text: str) -> int:
        direct = text.lower().find(self._OPEN)
        pseudo_m = self._PSEUDO_OPEN_FIND_RE.search(text)
        idx_pseudo = pseudo_m.start() if pseudo_m else -1
        if direct < 0 and idx_pseudo < 0:
            return -1
        if direct < 0:
            return idx_pseudo
        if idx_pseudo < 0:
            return direct
        return min(direct, idx_pseudo)

    def _feed_text(self, text: str) -> list[ParsedEvent]:
        # Handle escaped tags and pseudo openers (`plan title=` without `<`).
        self._buffer += self._normalize_plan_openers(text or "")
        out: list[ParsedEvent] = []
        while self._buffer:
            if self._state == "NORMAL":
                self._buffer = self._normalize_plan_openers(self._buffer)
                idx = self._find_open_index(self._buffer)
                if idx == -1:
                    emit, keep = self._split_partial_markers(self._buffer)
                    if emit:
                        out.append(ParsedEvent(ArtifactEvent.TEXT, content=emit))
                    self._buffer = keep
                    break
                if idx > 0:
                    out.append(
                        ParsedEvent(ArtifactEvent.TEXT, content=self._buffer[:idx])
                    )
                if self._buffer[idx : idx + len(self._OPEN)].lower() == self._OPEN:
                    self._tag_buffer = self._OPEN
                    self._buffer = self._buffer[idx + len(self._OPEN) :]
                else:
                    pseudo_m = self._PSEUDO_OPEN_FIND_RE.search(self._buffer, idx)
                    pseudo_len = (
                        len(pseudo_m.group(0)) if pseudo_m else len("plan title=")
                    )
                    self._tag_buffer = "<plan"
                    self._buffer = self._buffer[idx + pseudo_len :]
                self._state = "OPEN_TAG"
            elif self._state == "OPEN_TAG":
                gt = self._buffer.find(">")
                if gt == -1:
                    self._tag_buffer += self._buffer
                    self._buffer = ""
                    break
                self._tag_buffer += self._buffer[: gt + 1]
                self._buffer = self._buffer[gt + 1 :]
                attrs = self._parse_attrs(self._tag_buffer)
                if "identifier" not in attrs:
                    import uuid

                    attrs["identifier"] = "execution_plan_" + str(uuid.uuid4().hex[:6])
                attrs["type"] = "plan"
                self._current_attrs = attrs
                self._content_buffer = ""
                out.append(
                    ParsedEvent(
                        ArtifactEvent.ARTIFACT_START,
                        artifact_id=attrs.get("identifier"),
                        artifact_type="plan",
                        artifact_title=attrs.get("title") or "Execution Plan",
                        auto_execute=False,
                        filename=attrs.get("filename"),
                    )
                )
                self._state = "CONTENT"
            else:
                idx = self._buffer.find(self._CLOSE)
                if idx == -1:
                    emit, keep = self._split_partial(self._buffer, self._CLOSE)
                    if emit:
                        self._content_buffer += emit
                        out.append(
                            ParsedEvent(ArtifactEvent.ARTIFACT_CONTENT, content=emit)
                        )
                    self._buffer = keep
                    break
                chunk = self._buffer[:idx]
                if chunk:
                    self._content_buffer += chunk
                    out.append(
                        ParsedEvent(ArtifactEvent.ARTIFACT_CONTENT, content=chunk)
                    )
                self._buffer = self._buffer[idx + len(self._CLOSE) :]
                out.append(
                    ParsedEvent(
                        ArtifactEvent.ARTIFACT_END,
                        content=self._content_buffer,
                        artifact_id=self._current_attrs.get("identifier"),
                        artifact_type="plan",
                        artifact_title=self._current_attrs.get("title")
                        or "Execution Plan",
                        filename=self._current_attrs.get("filename"),
                    )
                )
                self._state = "NORMAL"
                self._tag_buffer = ""
                self._current_attrs = {}
                self._content_buffer = ""
        return out

    def _flush_self(self) -> list[ParsedEvent]:
        out: list[ParsedEvent] = []
        if self._state == "NORMAL":
            if self._buffer:
                out.append(ParsedEvent(ArtifactEvent.TEXT, content=self._buffer))
            self._buffer = ""
            return out

        if self._state == "OPEN_TAG":
            self._tag_buffer += self._buffer
            self._buffer = ""
            if ">" not in self._tag_buffer:
                self._tag_buffer += ">"
            tag = self._tag_buffer
            self._tag_buffer = ""
            attrs = self._parse_attrs(tag)
            if "identifier" not in attrs:
                import uuid

                attrs["identifier"] = "execution_plan_" + str(uuid.uuid4().hex[:6])
            attrs["type"] = "plan"
            self._current_attrs = attrs
            self._content_buffer = ""
            out.append(
                ParsedEvent(
                    ArtifactEvent.ARTIFACT_START,
                    artifact_id=attrs.get("identifier"),
                    artifact_type="plan",
                    artifact_title=attrs.get("title") or "Execution Plan",
                    auto_execute=False,
                    filename=attrs.get("filename"),
                )
            )
            self._state = "CONTENT"
            return out

        if self._buffer:
            self._content_buffer += self._buffer
            out.append(
                ParsedEvent(ArtifactEvent.ARTIFACT_CONTENT, content=self._buffer)
            )
        out.append(
            ParsedEvent(
                ArtifactEvent.ARTIFACT_END,
                content=self._content_buffer,
                artifact_id=self._current_attrs.get("identifier"),
                artifact_type="plan",
                artifact_title=self._current_attrs.get("title") or "Execution Plan",
                filename=self._current_attrs.get("filename"),
            )
        )
        self._state = "NORMAL"
        self._buffer = ""
        self._tag_buffer = ""
        self._current_attrs = {}
        self._content_buffer = ""
        return out

    def _parse_attrs(self, tag: str) -> dict:
        attrs = {}
        for match in self._ATTR_RE.finditer(tag):
            key = match.group(1)
            val = match.group(2) or match.group(3)
            attrs[key] = val
        return attrs

    @classmethod
    def _split_partial_markers(cls, text: str) -> tuple[str, str]:
        max_keep = 0
        for marker in cls._PARTIAL_OPEN_MARKERS:
            for keep_len in range(len(marker) - 1, 0, -1):
                if text.endswith(marker[:keep_len]):
                    max_keep = max(max_keep, keep_len)
                    break
        if max_keep:
            return text[:-max_keep], text[-max_keep:]
        return text, ""

    @staticmethod
    def _split_partial(text: str, marker: str) -> tuple[str, str]:
        max_keep = min(len(marker) - 1, len(text))
        for keep_len in range(max_keep, 0, -1):
            if text.endswith(marker[:keep_len]):
                return text[:-keep_len], text[-keep_len:]
        return text, ""
