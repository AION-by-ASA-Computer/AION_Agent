import os
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as OTLPHTTPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
try:
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
except ImportError:
    # Alcune versioni di OTel SDK non hanno l'exporter prometheus installato di default
    PrometheusMetricReader = None
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

from . import metrics


def _patch_prometheus_routing_for_included_router() -> None:
    """FastAPI 0.137+ stores included routers as ``_IncludedRouter`` without ``.path``.

    prometheus-fastapi-instrumentator <=8.0.0 assumes every matched route exposes
    ``.path`` and crashes on every HTTP request. Remove once upstream ships a fix:
    https://github.com/trallnag/prometheus-fastapi-instrumentator/issues/370
    """
    from typing import List, Optional

    from starlette.routing import Match, Mount
    from starlette.types import Scope

    import prometheus_fastapi_instrumentator.routing as routing

    if getattr(routing, "_aion_included_router_patch", False):
        return

    def _get_route_name(
        scope: Scope,
        routes: List,
        route_name: Optional[str] = None,
    ) -> Optional[str]:
        for route in routes:
            if hasattr(route, "effective_candidates"):
                match, child_scope, matched_route, route_context = route._match(scope)
                if match == Match.FULL:
                    route_name = (
                        route_context.path
                        if route_context is not None
                        else getattr(matched_route, "path", None)
                    )
                    if route_name is not None:
                        child_scope = {**scope, **child_scope}
                        target_route = (
                            route_context.starlette_route
                            if route_context is not None
                            else matched_route
                        )
                        if isinstance(target_route, Mount) and target_route.routes:
                            child_route_name = _get_route_name(
                                child_scope, target_route.routes, route_name
                            )
                            if child_route_name is None:
                                route_name = None
                            else:
                                route_name += child_route_name
                    return route_name
                if match == Match.PARTIAL and route_name is None:
                    route_name = (
                        route_context.path
                        if route_context is not None
                        else getattr(matched_route, "path", None)
                    )
                    continue

            match, child_scope = route.matches(scope)
            if match == Match.FULL:
                route_name = getattr(route, "path", None)
                child_scope = {**scope, **child_scope}
                if isinstance(route, Mount) and route.routes:
                    child_route_name = _get_route_name(
                        child_scope, route.routes, route_name
                    )
                    if child_route_name is None:
                        route_name = None
                    else:
                        route_name += child_route_name
                return route_name
            if match == Match.PARTIAL and route_name is None:
                route_name = getattr(route, "path", None)
        return None

    routing._get_route_name = _get_route_name
    routing._aion_included_router_patch = True


def init_observability(app):
    """Inizializza OTel (via OpenLit se disponibile, o OTel SDK standard) e Prometheus."""
    otel_enabled = os.getenv("AION_OTEL_ENABLED", "0") == "1"
    metrics_enabled = os.getenv("AION_METRICS_ENABLED", "1") == "1"
    
    resource = Resource.create({
        "service.name": os.getenv("AION_OTEL_SERVICE_NAME", "aion-agent"),
        "service.version": "3.0.0",
        "deployment.environment": os.getenv("AION_ENV", "dev"),
    })
    
    # Tracing
    openlit_success = os.environ.get("AION_OPENLIT_ACTIVE") == "1"
    if otel_enabled and not openlit_success:
        try:
            import openlit
            otlp_endpoint = os.getenv("AION_OTEL_ENDPOINT", "http://host.docker.internal:4317")
            service_name = os.getenv("AION_OTEL_SERVICE_NAME", "aion-agent")
            trace_content = os.getenv("AION_OTEL_TRACE_CONTENT", "1").strip().lower() in ("1", "true", "yes", "on")
            protocol = os.getenv("AION_OTEL_PROTOCOL", "grpc")

            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = otlp_endpoint
            os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = otlp_endpoint
            os.environ["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"] = otlp_endpoint

            if protocol == "grpc":
                os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"
                os.environ["OTEL_EXPORTER_OTLP_TRACES_PROTOCOL"] = "grpc"
                os.environ["OTEL_EXPORTER_OTLP_METRICS_PROTOCOL"] = "grpc"
            else:
                os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
                os.environ["OTEL_EXPORTER_OTLP_TRACES_PROTOCOL"] = "http/protobuf"
                os.environ["OTEL_EXPORTER_OTLP_METRICS_PROTOCOL"] = "http/protobuf"

            openlit.init(
                otlp_endpoint=otlp_endpoint,
                service_name=service_name,
                trace_content=trace_content,
            )
            openlit_success = True
            os.environ["AION_OPENLIT_ACTIVE"] = "1"
        except ImportError:
            pass
        except Exception:
            pass

    if otel_enabled and not openlit_success:
        trace_provider = TracerProvider(resource=resource)
        endpoint = os.getenv("AION_OTEL_ENDPOINT", "http://host.docker.internal:4317")
        protocol = os.getenv("AION_OTEL_PROTOCOL", "grpc")
        if protocol == "http":
            exporter = OTLPHTTPSpanExporter(endpoint=endpoint)
        else:
            exporter = OTLPSpanExporter(endpoint=endpoint)
        trace_provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(trace_provider)
        
        # Enable Haystack V2 native tracing
        # try:
        #     import haystack.tracing
        #     if not haystack.tracing.is_tracing_enabled():
        #         haystack.tracing.auto_enable_tracing()
        # except ImportError:
        #     pass
    elif not otel_enabled:
        # local dummy tracer provider when OTel is disabled
        trace_provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(trace_provider)
    
    # Metrics
    if metrics_enabled:
        _patch_prometheus_routing_for_included_router()
        # FastAPI Instrumentator for basic HTTP metrics
        Instrumentator().instrument(app).expose(app, endpoint=os.getenv("AION_METRICS_PATH", "/metrics"))
        
        from opentelemetry import metrics as otel_metrics
        
        if openlit_success:
            # Riusa il MeterProvider creato da OpenLit per non sovrascriverlo (altrimenti perdiamo gli strumenti OpenLit)
            meter_provider = otel_metrics.get_meter_provider()
            metrics.set_meter_provider(meter_provider)
        else:
            # Setup standard OTel MeterProvider
            from opentelemetry.sdk.metrics import MeterProvider as OTelMeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            
            readers = []
            if otel_enabled:
                endpoint = os.getenv("AION_OTEL_ENDPOINT", "http://localhost:4317")
                protocol = os.getenv("AION_OTEL_PROTOCOL", "grpc")
                try:
                    if protocol == "http":
                        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as OTLPHTTPMetricExporter
                        exporter = OTLPHTTPMetricExporter(endpoint=endpoint)
                    else:
                        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
                        exporter = OTLPMetricExporter(endpoint=endpoint)
                    
                    export_interval_str = os.getenv("AION_OTEL_METRIC_EXPORT_INTERVAL") or os.getenv("OTEL_METRIC_EXPORT_INTERVAL")
                    try:
                        export_interval = int(export_interval_str) if export_interval_str else 5000
                    except ValueError:
                        export_interval = 5000
                    
                    readers.append(PeriodicExportingMetricReader(exporter, export_interval_millis=export_interval))
                except Exception as e:
                    # Log or handle metrics exporter initialization errors gracefully
                    pass

            meter_provider = OTelMeterProvider(
                resource=resource,
                metric_readers=readers,
            )
            
            # Set global meter provider
            otel_metrics.set_meter_provider(meter_provider)
            
            # Also register with custom metrics module to initialize all backing OTel instruments
            metrics.set_meter_provider(meter_provider)

    
    # Auto-instrumentations
    if otel_enabled:
        FastAPIInstrumentor.instrument_app(app)
        try:
            # Assumes engine is created later, we instrument the generic SQLAlchemy module
            SQLAlchemyInstrumentor().instrument()
        except Exception:
            pass
        
        # Inizializza HTTPX o altri se necessari
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            HTTPXClientInstrumentor().instrument()
        except ImportError:
            pass
