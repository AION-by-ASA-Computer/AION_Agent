from fastmcp import FastMCP
import os
import sys

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.tools.grafana_tools import GrafanaTools
from src.config import config

mcp = FastMCP("AION Grafana Server")

# Initialize tools with central config
_tools = GrafanaTools(
    url=config.get("grafana.url"), api_key=config.get("grafana.api_key")
)


@mcp.tool()
def create_dashboard(
    dashboard_name: str, promql: str, panel_type: str = "timeseries"
) -> str:
    """Crea una nuova dashboard Grafana con una query specifica."""
    return _tools.create_dashboard(dashboard_name, promql, panel_type)


@mcp.tool()
def get_dashboard_uid(dashboard_name: str) -> str:
    """Cerca l'UID di una dashboard esistente tramite il suo nome."""
    return _tools.get_dashboard_uid(dashboard_name)


@mcp.tool()
def update_dashboard(dashboard_uid: str, new_title: str, promql: str) -> str:
    """Aggiorna una dashboard esistente aggiungendo o modificando un panel."""
    return _tools.update_dashboard(dashboard_uid, new_title, promql)


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
                f.write(f"\n--- GRAFANA CRASH ---\n{traceback.format_exc()}\n")
            raise e

    asyncio.run(main())
