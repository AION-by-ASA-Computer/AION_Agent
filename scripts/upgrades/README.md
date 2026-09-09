# scripts/upgrades/

Questa directory contiene i file di upgrade per-versione per il deploy GHCR.

## Convenzione

Ogni file si chiama `<versione_arrivo>.py` (es. `1.6.0.py`) e corrisponde
alla transizione dalla versione precedente nella lista release alla versione
indicata nel nome del file.

## Contratto minimo

```python
# scripts/upgrades/1.6.0.py
from pathlib import Path
import sys

# upgrade_lib viene scaricato da install.sh prima di eseguire questo file
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from upgrade_lib import UpgradeContext


def upgrade(ctx: UpgradeContext) -> None:
    # Aggiunge una nuova chiave .env con valore di default (idempotente)
    ctx.ensure_env_key("AION_NEW_FEATURE_FLAG", "0")

    # Rinomina una chiave esistente (no-op se assente)
    ctx.rename_env_key("AION_OLD_NAME", "AION_NEW_NAME")
```

## Come viene scoperto ed eseguito

`scripts/install.sh upgrade` scarica questo file via `fetch()` dal ref
`v<next>` prima di eseguire ogni hop. Se il file non esiste (HTTP 404),
lo step è un **no-op silenzioso** — la maggior parte delle release non
introduce breaking change al `.env` e non ha bisogno di un file qui.

## Quando aggiungere un file

Aggiungere `scripts/upgrades/<nuova_versione>.py` è un item della checklist
di rilascio **solo** quando la release introduce:
- Nuove chiavi `.env` obbligatorie con un valore di default consigliato
- Rinomina di chiavi `.env` esistenti
- Rimozione di chiavi `.env` deprecate
- Modifiche strutturali ai file di config in `config/`

Aggiungere il file nella stessa PR che introduce il breaking change.
Documentare in `CHANGELOG.md` con prefisso `feat!:` o nota `BREAKING CHANGE:`.
