import asyncio
import os
import sys

# Aggiungi root al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.engine import init_engine


async def seed_approval_rules():
    engine = init_engine()
    async with engine.begin() as conn:
        from sqlalchemy import text

        # Check if table exists
        res = await conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='approval_rules'"
            )
        )
        if not res.fetchone():
            print("Table 'approval_rules' not found. Ensure DB bootstrap is done.")
            return

        rules = [
            (
                "default",
                "agent_db_drop_table",
                ".*",
                "ask",
                "admin",
                "Operazione potenzialmente distruttiva: richiede conferma esplicita dell'utente",
            ),
            (
                "default",
                "agent_db_alter_table",
                '.*"operation":\\s*"DROP_COLUMN".*',
                "ask",
                "admin",
                "Rimozione colonna può causare perdita dati: richiede conferma",
            ),
            (
                "default",
                "agent_db_create_table",
                ".*",
                "allow",
                "admin",
                "Creazione tabella non è distruttiva",
            ),
            ("default", "agent_db_insert", ".*", "allow", "admin", None),
            ("default", "agent_db_insert_batch", ".*", "allow", "admin", None),
            ("default", "agent_db_query", ".*", "allow", "admin", None),
            (
                "default",
                "agent_db_alter_table",
                '.*"operation":\\s*"ADD_COLUMN".*',
                "allow",
                "admin",
                "Aggiunta colonna non distruttiva",
            ),
        ]

        for rule in rules:
            await conn.execute(
                text("""
                INSERT OR REPLACE INTO approval_rules (tenant_id, tool_name, input_pattern, decision, source, rationale, uses)
                VALUES (:tenant_id, :tool_name, :input_pattern, :decision, :source, :rationale, 0)
            """),
                {
                    "tenant_id": rule[0],
                    "tool_name": rule[1],
                    "input_pattern": rule[2],
                    "decision": rule[3],
                    "source": rule[4],
                    "rationale": rule[5],
                },
            )

        print(f"Seeded {len(rules)} approval rules for Agent DB.")


if __name__ == "__main__":
    asyncio.run(seed_approval_rules())
