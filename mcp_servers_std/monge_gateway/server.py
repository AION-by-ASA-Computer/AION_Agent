"""
MCP Server: Monge DMZ Gateway.
Permette all'agente di interrogare il Gateway in DMZ per eseguire query SQL
e leggere lo schema di 'automa_monge' / 'Storicofatturati'.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

import requests
from fastmcp import FastMCP

mcp = FastMCP("AION Monge DMZ Gateway")

DMZ_GATEWAY_URL = os.getenv("DMZ_GATEWAY_URL", "http://IP_MACCHINA_DMZ:8000")
DMZ_GATEWAY_API_KEY = os.getenv("DMZ_GATEWAY_API_KEY", "")


def get_gateway_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("DMZ_GATEWAY_API_KEY", DMZ_GATEWAY_API_KEY)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers

@mcp.tool()
def list_available_databases() -> Dict[str, Any]:
    """
    Recupera l'elenco dei database disponibili e interrogabili sul Gateway DMZ (es. 'automa_monge', 'StoricoFatturati').
    """
    base_url = os.getenv("DMZ_GATEWAY_URL", DMZ_GATEWAY_URL).rstrip("/")
    url = f"{base_url}/api/v1/databases"
    try:
        res = requests.get(url, headers=get_gateway_headers(), timeout=15)
        if res.status_code == 200:
            return res.json()
        return {"error": f"Gateway ha risposto con codice {res.status_code}: {res.text}"}
    except Exception as e:
        return {"error": f"Impossibile raggiungere il Gateway DMZ su {url}: {str(e)}"}


@mcp.tool()
def get_database_catalog(db_name: str = "automa_monge") -> Dict[str, Any]:
    """
    Recupera l'intero catalogo sintetico del database indicato (tabelle, viste, colonne chiave)
    in una sola chiamata ultra-rapida.
    db_name: nome del database target (es. 'automa_monge' o 'StoricoFatturati').
    """
    base_url = os.getenv("DMZ_GATEWAY_URL", DMZ_GATEWAY_URL).rstrip("/")
    url = f"{base_url}/api/v1/catalog"
    try:
        res = requests.get(
            url,
            params={"db": db_name},
            headers=get_gateway_headers(),
            timeout=15,
        )
        if res.status_code == 200:
            return res.json()
        return {"error": f"Gateway ha risposto con codice {res.status_code}: {res.text}"}
    except Exception as e:
        return {"error": f"Impossibile raggiungere il Gateway DMZ su {url}: {str(e)}"}


@mcp.tool()
def get_table_schema(table_name: str, db_name: str = "StoricoFatturati") -> Dict[str, Any]:
    """
    Recupera lo schema (colonne, tipi, vincoli, conteggio righe) per una tabella specifica nel database indicato.
    table_name: nome della tabella o vista (es. 'Giacenze' su automa_monge o 'Fatturato' su StoricoFatturati).
    db_name: nome del database target (es. 'automa_monge' o 'StoricoFatturati').
    """
    base_url = os.getenv("DMZ_GATEWAY_URL", DMZ_GATEWAY_URL).rstrip("/")
    url = f"{base_url}/api/v1/schema"
    try:
        res = requests.get(
            url,
            params={"table_name": table_name, "db": db_name},
            headers=get_gateway_headers(),
            timeout=15,
        )
        if res.status_code == 200:
            return res.json()
        return {"error": f"Gateway ha risposto con codice {res.status_code}: {res.text}"}
    except Exception as e:
        return {"error": f"Impossibile raggiungere il Gateway DMZ su {url}: {str(e)}"}


@mcp.tool()
def execute_db_query(
    sql_query: str,
    db_name: str = "automa_monge",
    max_rows: int = 200,
) -> Dict[str, Any]:
    """
    Esegue una query SQL (solo SELECT) sul database specificato tramite il Gateway in DMZ.
    sql_query: query SQL (SELECT con TOP/LIMIT, WITH, COUNT, GROUP BY).
    db_name: nome del database target (es. 'automa_monge' per logistica/magazzino, 'StoricoFatturati' per vendite/fatture).
    max_rows: numero massimo di righe da restituire (default 200).
    """
    base_url = os.getenv("DMZ_GATEWAY_URL", DMZ_GATEWAY_URL).rstrip("/")
    url = f"{base_url}/api/v1/query"
    payload = {"sql": sql_query, "db": db_name, "max_rows": max_rows}
    try:
        res = requests.post(
            url, json=payload, headers=get_gateway_headers(), timeout=35
        )
        if res.status_code == 200:
            return res.json()
        return {
            "success": False,
            "error": f"Errore Gateway [{res.status_code}]: {res.text}",
        }
    except Exception as e:
        return {"success": False, "error": f"Errore di rete verso Gateway DMZ: {str(e)}"}


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
            os.makedirs("data", exist_ok=True)
            with open("data/mcp_debug.log", "a", encoding="utf-8") as f:
                f.write(f"\n--- MONGE GATEWAY CRASH ---\n{traceback.format_exc()}\n")
            raise e

    asyncio.run(main())
