# mcp_servers/agent_db/ltm_sync.py
"""Legacy in-process MemPalace hook. Prefer `ltm_notifier.post_structured_drawer_sync` → FastAPI `/internal/agent-db/sync-drawer`."""

import json
from typing import Dict, Any


class AgentDBLTMSync:
    def __init__(self, mcp_client=None):
        self._mempalace_client = mcp_client

    async def notify_schema_change(
        self,
        user_id: str,
        schema_name: str,
        table_name: str,
        operation: str,
        summary: Dict[str, Any],
    ):
        """Notifies MemPalace of a schema change."""
        if not self._mempalace_client:
            print(
                f"[LTM Sync Mock] Schema change: {schema_name}.{table_name} ({operation})"
            )
            return

        content = self._format_schema_summary(schema_name, table_name, summary)
        try:
            await self._mempalace_client.call(
                "mempalace_write_drawer",
                {
                    "wing": "structured_data",
                    "key": f"{user_id}::{schema_name}::{table_name}",
                    "content": content,
                    "tags": ["agent_db", schema_name, table_name, "schema"],
                },
            )
        except Exception as e:
            print(f"[LTM Sync Error] Failed to sync schema change: {e}")

    def _format_schema_summary(
        self, schema_name: str, table_name: str, summary: Dict[str, Any]
    ) -> str:
        cols = summary.get("columns", [])
        col_desc = ", ".join([f"{c['name']} ({c['column_type']})" for c in cols])
        return (
            f"[structured_data] Schema: {schema_name} | Tabella: {table_name}\n"
            f"Colonne: {col_desc}\n"
            f"Righe: {summary.get('row_count', 0)} | Ultima modifica: {summary.get('updated_at', 'N/A')}"
        )
