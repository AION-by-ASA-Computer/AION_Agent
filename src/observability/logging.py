import structlog
import logging
import sys
import os
from opentelemetry import trace
from structlog.stdlib import ProcessorFormatter


def _resolve_log_level() -> int:
    raw = (os.getenv("AION_LOG_LEVEL") or "INFO").strip().upper()
    return getattr(logging, raw, logging.INFO)


def _resolve_log_format() -> str:
    """json for collectors/CI; text on interactive terminals when unset."""
    raw = (os.getenv("AION_LOG_FORMAT") or "").strip().lower()
    if raw in ("json", "text", "console"):
        return "json" if raw == "json" else "text"
    if sys.stdout.isatty():
        return "text"
    return "json"


def setup_logging():
    log_format = _resolve_log_format()
    log_level = _resolve_log_level()

    # 1. Define shared processors for both structlog and standard library logs
    def add_otel_context(_, __, event_dict):
        span = trace.get_current_span()
        if span.is_recording():
            ctx = span.get_span_context()
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")

            # Enrich log with trace/span attributes if present
            attrs = getattr(span, "attributes", None)
            if attrs:
                for k in (
                    "aion.profile",
                    "aion.session_id",
                    "aion.user_id",
                    "aion.tenant_id",
                    "tool.name",
                    "tool.mcp_server",
                    "tool.output",
                    "tool.error",
                    "file.name",
                    "extract.status",
                ):
                    if k in attrs:
                        val = attrs[k]
                        event_dict[k] = val
                        clean_key = k.split(".")[-1]
                        event_dict[clean_key] = val
        return event_dict

    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_otel_context,
    ]

    # 2. Configure structlog
    structlog.configure(
        processors=shared_processors
        + [
            ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 3. Configure standard library root logger
    root_logger = logging.getLogger()

    # Remove existing handlers to avoid duplicates or unformatted console output
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    # Add our unified console stream handler
    console_handler = logging.StreamHandler(sys.stdout)

    # Configure formatter based on log format
    if log_format == "json":
        formatter = ProcessorFormatter(
            foreign_pre_chain=shared_processors
            + [
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
            ],
            processor=structlog.processors.JSONRenderer(),
        )
    else:
        formatter = ProcessorFormatter(
            foreign_pre_chain=shared_processors
            + [
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
            ],
            processor=structlog.dev.ConsoleRenderer(
                colors=sys.stdout.isatty(),
                exception_formatter=structlog.dev.plain_traceback,
            ),
        )

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    root_logger.setLevel(log_level)

    # 4. Propagate Uvicorn & FastAPI loggers to the root logger
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        std_logger = logging.getLogger(name)
        std_logger.handlers = []
        std_logger.propagate = True
        std_logger.setLevel(log_level)

    # 5. Prevent Uvicorn from disabling our loggers during startup
    for name in list(logging.root.manager.loggerDict.keys()):
        # Salviamo tutti i logger del nostro progetto (aion, src, agent)
        if (
            name.startswith("aion")
            or name.startswith("src")
            or name.startswith("agent")
        ):
            logger = logging.getLogger(name)
            logger.disabled = False
            logger.propagate = True
            logger.setLevel(log_level)

    # 6. Configure direct OTLP log exporting if enabled
    otel_enabled = os.getenv("AION_OTEL_ENABLED", "0") == "1"
    if otel_enabled:
        try:
            from opentelemetry._logs import set_logger_provider
            from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
            from opentelemetry.sdk._logs.export import (
                BatchLogRecordProcessor,
                SimpleLogRecordProcessor,
            )
            from opentelemetry.sdk.resources import Resource

            resource = Resource.create(
                {
                    "service.name": os.getenv("AION_OTEL_SERVICE_NAME", "aion-agent"),
                    "service.version": "3.0.0",
                    "deployment.environment": os.getenv("AION_ENV", "dev"),
                }
            )

            # Create provider and exporter
            logger_provider = LoggerProvider(resource=resource)
            set_logger_provider(logger_provider)

            endpoint = os.getenv(
                "AION_OTEL_ENDPOINT", "http://host.docker.internal:4317"
            )
            protocol = os.getenv("AION_OTEL_PROTOCOL", "grpc")

            if protocol == "http":
                from opentelemetry.exporter.otlp.proto.http._log_exporter import (
                    OTLPLogExporter,
                )
            else:
                from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
                    OTLPLogExporter,
                )

            exporter = OTLPLogExporter(endpoint=endpoint)

            # Usiamo sempre BatchLogRecordProcessor per evitare di bloccare sincronicamente il thread
            # principale di esecuzione in caso di latenza o timeout del collector (specialmente su Windows/WSL2).
            logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

            # Remove existing OTel LoggingHandlers to avoid duplicates
            for h in list(root_logger.handlers):
                if isinstance(h, LoggingHandler):
                    root_logger.removeHandler(h)

            # Add OTel LoggingHandler to root logger
            otel_handler = LoggingHandler(
                level=logging.DEBUG, logger_provider=logger_provider
            )
            root_logger.addHandler(otel_handler)
        except Exception as e:
            # Prevent failures from blocking application startup
            logging.warning("Errore durante l'inizializzazione del logger OTLP: %s", e)
