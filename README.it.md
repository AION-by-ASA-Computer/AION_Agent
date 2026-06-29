# AION Agent

Agente conversazionale con pipeline MCP, memoria (STM/LTM), chat-ui (Next.js) e admin UI.

**AION · ASA:** sito e riferimento commerciale — **[https://aion-asa.com](https://aion-asa.com)**

> La documentazione di prodotto in inglese è nel [README principale](README.md).

## Documentazione tecnica

L'indice e le guide vivono nella cartella **[`docs/`](docs/)** del repository: è la **stessa sorgente** che alimenta il sito di documentazione (progetto Docusaurus in [`website/`](website/)).

| Dove lavori | Cosa usi |
|-------------|----------|
| **Modifica contenuti** | Indice in [`docs/index.md`](docs/index.md); capitoli per area in sottocartelle (`docs/architecture/`, `docs/configuration/`, …). Vedi [`docs/standard/authoring.md`](docs/standard/authoring.md) per le convenzioni. |
| **Anteprima locale del sito doc** | Da [`website/`](website/): `pnpm install` poi `pnpm start` oppure `pnpm build`. |

## Avvio rapido (Setup guidato)

```bash
./scripts/setup-aion-env.sh         # Modalità Standard
./scripts/setup-aion-env.sh --advanced   # Modalità Avanzata (Redis, S3, etc.)
```

### Avvio servizi

```bash
uvicorn src.api.main:app --reload --reload-exclude data/sessions   # Backend (8001)
cd chat-ui && pnpm dev    # Chat UI (8003)
cd admin-ui && pnpm dev --webpack   # Admin UI (3870)
```

Il client principale è `chat-ui/` (Next.js).

## Upgrade operativo

```bash
./scripts/upgrade-aion.sh
./scripts/upgrade-aion.sh --dry-run
```

Vedi [CONTRIBUTING.md](CONTRIBUTING.md) per setup sviluppo e test.
