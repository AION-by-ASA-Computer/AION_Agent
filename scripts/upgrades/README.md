# scripts/upgrades/

Questa directory contiene i file di upgrade per-versione per il deploy GHCR.

## Come vengono eseguiti

`install.sh upgrade` avvia un container usa e getta dalla **nuova immagine GHCR**
(non scarica script da GitHub) con i volumi dell'host montati in rw:

```bash
docker run --rm \
  -v "$PWD/.env:/app/.env:rw" \
  -v "$PWD/config:/app/config:rw" \
  -v "$PWD/mcp_servers:/app/mcp_servers:rw" \
  -v "$PWD/data:/app/data:rw" \
  --entrypoint python3 \
  ghcr.io/aion-by-asa-computer/aion-backend:<next> \
  scripts/upgrade_runner.py --from <prev> --to <next>
```

`upgrade_runner.py` (entrypoint del container) esegue in sequenza:
1. Sync `config_std/` → `config/` (merge non-distruttivo)
2. Sync `mcp_servers_std/` → `mcp_servers/` (merge non-distruttivo)
3. `scripts/upgrades/<next>.py` se presente (con UpgradeContext — pieno stack Python)
4. Aggiorna `AION_VERSION=<next>` nel `.env` montato

## Convenzione

Ogni file si chiama `<versione_arrivo>.py` (es. `1.6.0.py`).
Espone una sola funzione: `def upgrade(ctx: UpgradeContext) -> None`.

```python
# scripts/upgrades/1.6.0.py
from pathlib import Path
import sys

# upgrade_lib è già nel sys.path (aggiunto da upgrade_runner.py)
from upgrade_lib import UpgradeContext


def upgrade(ctx: UpgradeContext) -> None:
    # Disponibile: pieno stack Python di AION (SQLAlchemy, FastAPI, ecc.)
    # I volumi .env, config/, mcp_servers/, data/ sono montati in rw

    # Aggiunge una nuova chiave .env con valore di default (idempotente)
    ctx.ensure_env_key("AION_NEW_FEATURE_FLAG", "0")

    # Rinomina una chiave esistente (no-op se assente)
    ctx.rename_env_key("AION_OLD_NAME", "AION_NEW_NAME")

    # Operazioni più complesse con l'intero stack Python:
    # from src.data.models import MyModel
    # ...
```

## Quando aggiungere un file qui

**Solo** quando la release introduce:
- Nuove chiavi `.env` obbligatorie con un valore di default consigliato
- Rinomina o rimozione di chiavi `.env` esistenti
- Modifiche strutturali ai file in `config/`
- Migrazioni di dati che richiedono codice Python (es. trasformazione del DB)

La **maggior parte delle release non ha bisogno di un file qui** — `upgrade_runner.py`
gestisce già automaticamente la sync di `config_std/` e `mcp_servers_std/`, che copre
il 90% dei casi.

Aggiungere il file nella stessa PR che introduce il breaking change e documentarlo
in `CHANGELOG.md` con `BREAKING CHANGE:`.

## Note su config_std/ e mcp_servers_std/

`upgrade_runner.py` sincronizza queste directory automaticamente ad ogni hop,
con merge non-distruttivo: copia solo i file **assenti** nella directory di
destinazione. I file personalizzati dall'utente non vengono mai sovrascritti.
