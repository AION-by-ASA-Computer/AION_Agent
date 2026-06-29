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
    Se manca un modulo critico (es. agent_db), esegue sync_mcp_servers in modalità safe.
    """
    marker = _ROOT / "mcp_servers" / "agent_db" / "db_manager.py"
    if marker.is_file():
        return
    std_marker = _ROOT / "mcp_servers_std" / "agent_db" / "db_manager.py"
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

        import openlit

        openlit.init()
        os.environ["AION_OPENLIT_ACTIVE"] = "1"
    except ImportError:
        pass
    except Exception:
        pass
