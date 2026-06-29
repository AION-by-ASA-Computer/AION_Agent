import asyncio
import os
from src.data.engine import get_engine
from src.data.models import Base


async def init_unified_db():
    print("Inizializzazione database unificato...")
    engine = get_engine()
    async with engine.begin() as conn:
        # Crea tutte le tabelle definite nei modelli
        await conn.run_sync(Base.metadata.create_all)
    print("Database unificato inizializzato con successo!")


if __name__ == "__main__":
    asyncio.run(init_unified_db())
