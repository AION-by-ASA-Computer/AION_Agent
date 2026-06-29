from fastmcp import FastMCP
import os
import sys
from typing import List, Optional, Dict, Any

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.tools.prometheus_tools import PrometheusTools
from src.config import config

mcp = FastMCP("AION Charts Server")

# Initialize Prometheus tools if configured
prom_api_url = config.get("prometheus.api_url")
_prom_tools = None
if prom_api_url:
    _prom_tools = PrometheusTools(
        api_url=prom_api_url,
        timeout=config.get("prometheus.timeout", 10)
    )

@mcp.tool()
def render_chart(
    query: str,
    data: Optional[Any] = None,
    chart_kind: str = "line",
    x_key: str = "index",
    series_keys: Optional[Any] = None,
    stacked: bool = False,
    legend_off: bool = False,
    y_label: str = "",
) -> dict:
    """
    Create a chart for the current session. Displays data interactively in chat-ui (Recharts).
    
    Parameters:
    - query: Descriptive chart title or PromQL query (when querying Prometheus).
    - data: List or JSON string of dicts/records for arbitrary data (es. distribuzioni, statistiche).
    - chart_kind: Chart type: 'line' (comparison/time), 'area' (volumes), o 'bar' (distributions/bars).
    - x_key: Record key for the X axis (default: 'index').
    - series_keys: List or JSON string of columns to display (default: all except x_key).
    - stacked: If True, stack series (relevant for 'area' and 'bar').
    - legend_off: If True, hide the legend.
    - y_label: Y-axis label.
    """
    import json

    chart_kind_val = (chart_kind or "line").strip().lower()
    if chart_kind_val not in ("line", "area", "bar"):
        chart_kind_val = "line"

    parsed_data = None
    if data is not None:
        if isinstance(data, str):
            try:
                parsed_data = json.loads(data)
            except json.JSONDecodeError as e:
                return {"error": f"Invalid JSON string passed to 'data': {str(e)}"}
        else:
            parsed_data = data

    parsed_series_keys = None
    if series_keys is not None:
        if isinstance(series_keys, str):
            try:
                parsed_series_keys = json.loads(series_keys)
            except json.JSONDecodeError as e:
                return {"error": f"Invalid JSON string passed to 'series_keys': {str(e)}"}
        else:
            parsed_series_keys = series_keys

    if parsed_data is not None:
        out = {
            "query": query,
            "data": parsed_data,
            "chart_kind": chart_kind_val,
            "x_key": x_key or "index",
            "stacked": bool(stacked),
            "legend_off": bool(legend_off),
        }
        if y_label:
            out["y_label"] = y_label
        if parsed_series_keys:
            out["series_keys"] = list(parsed_series_keys)
        return out

    # Se data è None, proviamo a recuperarlo da Prometheus se configurato
    if _prom_tools:
        chart_data = _prom_tools.get_chart_data(query)
        if not chart_data:
            return {"error": f"No Prometheus data found for query: {query}"}

        out = {
            "query": chart_data.query,
            "data": chart_data.dataframe.reset_index().to_dict(orient="records"),
            "range_seconds": chart_data.range_seconds,
            "step_seconds": chart_data.step_seconds,
            "chart_kind": chart_kind_val,
            "x_key": "index",
            "stacked": bool(stacked),
            "legend_off": bool(legend_off),
        }
        if y_label:
            out["y_label"] = y_label
        elif chart_data.y_label:
            out["y_label"] = chart_data.y_label

        if parsed_series_keys:
            out["series_keys"] = list(parsed_series_keys)
        elif chart_data.series_keys:
            out["series_keys"] = chart_data.series_keys
        return out

    return {
        "error": "Incomplete instruction: 'data' not provided and Prometheus server not configured."
    }

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
                    mcp._mcp_server.create_initialization_options()
                )
        except Exception as e:
            with open("data/mcp_debug.log", "a") as f:
                f.write(f"\n--- CHARTS SERVER CRASH ---\n{traceback.format_exc()}\n")
            raise e

    asyncio.run(main())
