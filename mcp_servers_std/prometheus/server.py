from fastmcp import FastMCP
import os
import sys
from typing import List, Optional

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.tools.prometheus_tools import PrometheusTools
from src.config import config

mcp = FastMCP("AION Prometheus Server")

# Initialize tools with central config
_tools = PrometheusTools(
    api_url=config.get("prometheus.api_url"),
    timeout=config.get("prometheus.timeout", 10),
)


@mcp.tool()
def search_metric(metric_name: str) -> str:
    """Cerca metriche in Prometheus per nome o pattern."""
    return _tools.search_metric(metric_name)


@mcp.tool()
def get_metric_labels(metric_name: str, limit: int = 20) -> str:
    """Recupera tutte le label/serie disponibili per una metrica specifica."""
    return _tools.get_metric_labels(metric_name, limit)


@mcp.tool()
def execute_promql(query: str) -> str:
    """Esegue una query PromQL istantanea e restituisce il risultato testuale."""
    return _tools.execute_promql(query)


if __name__ == "__main__":
    import asyncio
    import traceback
    from mcp.server.stdio import stdio_server

    async def main():
        try:
            async with stdio_server() as (read_stream, write_stream):
                await mcp._mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp._mcp_server.create_initialization_options(),
                )
        except Exception as e:
            with open("data/mcp_debug.log", "a") as f:
                f.write(f"\n--- PROMETHEUS CRASH ---\n{traceback.format_exc()}\n")
            raise e

    asyncio.run(main())
