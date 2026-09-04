"""Carica `.env` dalla root del progetto (una volta). Importare prima di altri moduli che leggono os.environ."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Import assoluti tipo ``mcp_servers.agent_db`` (cartella locale, non in site-packages).
_root_s = str(_ROOT)
if _root_s not in sys.path:
    sys.path.insert(0, _root_s)


def _ensure_mcp_servers_from_std() -> None:
    """
    ``mcp_servers/`` è gitignored e va popolata da ``mcp_servers_std/`` (come config/ da config_std/).
    Se manca un modulo critico (es. session_sandbox), esegue sync_mcp_servers in modalità safe.
    """
    marker = _ROOT / "mcp_servers" / "session_sandbox" / "server.py"
    if marker.is_file():
        return
    std_marker = _ROOT / "mcp_servers_std" / "session_sandbox" / "server.py"
    if not std_marker.is_file():
        return
    script = _ROOT / "scripts" / "sync_mcp_servers.py"
    if not script.is_file():
        return
    import subprocess

    subprocess.run(
        [sys.executable, str(script)],
        cwd=str(_ROOT),
        check=False,
    )


_ensure_mcp_servers_from_std()

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
    load_dotenv(_ROOT / ".env.local", override=False)

    from src.runtime.env_sync import (
        apply_merged_env_to_os,
        reconcile_runtime_env_on_boot,
    )

    reconcile_runtime_env_on_boot()
    apply_merged_env_to_os()
except ImportError:
    pass
except Exception:
    # Fallback: legacy runtime.env override if reconcile/apply fails at import time.
    try:
        from dotenv import load_dotenv

        data_dir = os.environ.get("AION_DATA_DIR", "data")
        data_path = Path(data_dir)
        if not data_path.is_absolute():
            data_path = _ROOT / data_path
        runtime_env = data_path / "runtime.env"
        if runtime_env.is_file():
            load_dotenv(runtime_env, override=True)
    except ImportError:
        pass

# Inizializzazione precoce di OpenLit (dopo load_dotenv così AION_OTEL_* è disponibile).
if (
    os.getenv("AION_OTEL_ENABLED", "0") == "1"
    and os.environ.get("AION_OPENLIT_ACTIVE") != "1"
):
    try:
        otlp_endpoint = os.getenv(
            "AION_OTEL_ENDPOINT", "http://host.docker.internal:4317"
        )
        service_name = os.getenv("AION_OTEL_SERVICE_NAME", "aion-agent")
        protocol = os.getenv("AION_OTEL_PROTOCOL", "grpc")

        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = otlp_endpoint

        if protocol == "grpc":
            os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"
            os.environ["OTEL_EXPORTER_OTLP_TRACES_PROTOCOL"] = "grpc"
            os.environ["OTEL_EXPORTER_OTLP_METRICS_PROTOCOL"] = "grpc"
        else:
            os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
            os.environ["OTEL_EXPORTER_OTLP_TRACES_PROTOCOL"] = "http/protobuf"
            os.environ["OTEL_EXPORTER_OTLP_METRICS_PROTOCOL"] = "http/protobuf"

        os.environ["OTEL_RESOURCE_ATTRIBUTES"] = f"service.name={service_name}"
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_METRICS_EXPORTER"] = "otlp"
        os.environ["OTEL_LOGS_EXPORTER"] = "none"

        # Setup standard OTel MeterProvider early so OpenLit registers its metrics on it
        try:
            from opentelemetry import metrics as otel_metrics
            from opentelemetry.sdk.metrics import MeterProvider as OTelMeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource

            resource = Resource.create(
                {
                    "service.name": service_name,
                    "service.version": "3.0.0",
                    "deployment.environment": os.getenv("AION_ENV", "dev"),
                }
            )

            readers = []
            if protocol == "http":
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                    OTLPMetricExporter as OTLPHTTPMetricExporter,
                )

                exporter = OTLPHTTPMetricExporter(endpoint=otlp_endpoint)
            else:
                from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                    OTLPMetricExporter,
                )

                exporter = OTLPMetricExporter(endpoint=otlp_endpoint)

            export_interval_str = os.getenv(
                "AION_OTEL_METRIC_EXPORT_INTERVAL"
            ) or os.getenv("OTEL_METRIC_EXPORT_INTERVAL")
            try:
                export_interval = (
                    int(export_interval_str) if export_interval_str else 5000
                )
            except ValueError:
                export_interval = 5000

            readers.append(
                PeriodicExportingMetricReader(
                    exporter, export_interval_millis=export_interval
                )
            )

            meter_provider = OTelMeterProvider(
                resource=resource,
                metric_readers=readers,
            )
            otel_metrics.set_meter_provider(meter_provider)
        except Exception:
            pass

        import openlit

        openlit.init(
            otlp_endpoint=otlp_endpoint,
        )
        os.environ["AION_OPENLIT_ACTIVE"] = "1"
    except ImportError:
        pass
    except Exception:
        pass
