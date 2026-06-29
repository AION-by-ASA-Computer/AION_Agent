import io
import os
import logging
from pypdf import PdfReader
import pandas as pd

logger = logging.getLogger(__name__)


def extract_text_from_bytes(content: bytes, filename: str, mime_type: str) -> str:
    """Extract text from various file formats."""
    otel_enabled = os.getenv("AION_OTEL_ENABLED", "0") == "1"
    tracer = None
    if otel_enabled:
        try:
            from opentelemetry import trace

            tracer = trace.get_tracer("aion.document")
        except ImportError:
            pass

    from contextlib import nullcontext

    span_ctx = nullcontext()
    if tracer:
        try:
            span_ctx = tracer.start_as_current_span("document.extract_text")
        except Exception:
            pass

    with span_ctx as span:
        if span and span.is_recording():
            try:
                span.set_attribute("file.name", filename)
                span.set_attribute("file.mime", mime_type)
                span.set_attribute("file.size_bytes", len(content))
            except Exception:
                pass

        logger.info(
            "document_extract_start filename=%s mime_type=%s size_bytes=%d",
            filename,
            mime_type,
            len(content),
            extra={
                "file.name": filename,
                "file.mime": mime_type,
                "file.size_bytes": len(content),
            },
        )

        try:
            if "pdf" in mime_type or filename.lower().endswith(".pdf"):
                reader = PdfReader(io.BytesIO(content))
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                out = text

            elif "csv" in mime_type or filename.lower().endswith(".csv"):
                df = pd.read_csv(io.BytesIO(content))
                out = df.to_string()

            elif "text" in mime_type or filename.lower().endswith(
                (".txt", ".md", ".json")
            ):
                out = content.decode("utf-8", errors="ignore")

            else:
                out = f"(Formato non supportato per {filename})"

            if span and span.is_recording():
                try:
                    span.set_attribute("extract.status", "success")
                    span.set_attribute("extract.char_count", len(out))
                except Exception:
                    pass

            logger.info(
                "document_extract_success filename=%s char_count=%d",
                filename,
                len(out),
                extra={
                    "file.name": filename,
                    "extract.status": "success",
                    "extract.char_count": len(out),
                },
            )
            return out

        except Exception as e:
            if span and span.is_recording():
                try:
                    from opentelemetry.trace import Status, StatusCode

                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.set_attribute("extract.status", "error")
                except Exception:
                    pass

            logger.error(
                "document_extract_error filename=%s error=%s",
                filename,
                str(e),
                extra={
                    "file.name": filename,
                    "extract.status": "error",
                    "error": str(e),
                },
            )
            return f"(Error while extracting from {filename}: {e})"


def query_docs(query: str, documents: list) -> str:
    """Very simple search over the provided documents."""
    if not documents:
        return "No documents uploaded."

    results = []
    for doc in documents:
        text = extract_text_from_bytes(doc["content"], doc["name"], doc["type"])
        if query.lower() in text.lower():
            # Find snippet
            idx = text.lower().find(query.lower())
            start = max(0, idx - 200)
            end = min(len(text), idx + 1000)
            snippet = text[start:end]
            results.append(f"--- Da {doc['name']} ---\n...{snippet}...")

    if not results:
        # If no direct match, return a summary of available docs
        summary = "Nessuna corrispondenza esatta trovata. Documenti disponibili:\n"
        for doc in documents:
            summary += f"- {doc['name']} ({doc['type']})\n"
        return summary

    return "\n\n".join(results)
