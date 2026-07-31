---
sidebar_position: 2
title: Catalogo connettori MCP consigliati
description: YAML curato, endpoint admin, MCP Hub e checklist QA / sicurezza per integrazioni aziendali.
---

# Catalogo connettori MCP consigliati

AION modella la **connettività enterprise** tramite **server MCP** (registry + marketplace in Admin). Lo **schema credenziali** per server arbitrari è rilevato automaticamente da README, `.env.example` e sorgenti ([`src/mcp_credential_discovery.py`](../../src/mcp_credential_discovery.py)).

Il file opzionale **`config/mcp_connector_catalog.yaml`** elenca integrazioni curate con:

- `id`, `title`, `description`, `category`;
- link alla documentazione del vendor (`official_doc_url`, `mcp_upstream_docs_url`);
- **`registry_search_hint`**: stringa usata dal pulsante «Cerca nel marketplace» nella pagina **Admin → MCP Hub**;
- **`example_registry_block`**: snippet commentato da copiare in `config/mcp_registry.local.yaml` dopo audit del pacchetto scelto;
- **`required_env` / `optional_env`**: solo **nomi** variabili (mai segreti in git), per connettori stdio;
- **`credential_fields`**: campi per-utente (PAT, API key, …) — **non** usare `OAUTH_TOKEN` quando `auth_type: oauth2` (il token OAuth è gestito dal flusso dedicato);
- **`runtime_env_aliases`** (opzionale): mappa **nomi env attesi dal processo MCP** verso **chiavi alternative** (es. snippet da Claude Code / altri client). All’avvio stdio, se la chiave destinazione è vuota e una sorgente è valorizzata, viene copiato il valore — tutto dichiarativo nel YAML, senza codice per connettore.

## Override locale

**`config/mcp_connector_catalog.yaml`** (stessa struttura `version` + `connectors`) è opzionale: se assente in `config/`, il backend carica il template committato **`config_std/mcp_connector_catalog.yaml`**.

### Connettori remoti OAuth

Per un endpoint MCP hosted con login OAuth, basta dichiarare nel YAML:

```yaml
- id: my_service
  title: My Service          # etichetta UI: "Accedi con My Service"
  install_type: remote
  remote_url: https://mcp.example.com/mcp
  auth_type: oauth2          # abilita OAuth in chat-ui, nasconde PAT/OAUTH_TOKEN
  oauth_provider: my_service # opzionale; default = id
  featured_remote: true      # card in Admin → MCP Hub → Marketplace
  default_credential_mode: per_user
```

Non serve codice né stringhe i18n per servizio: `title` e `auth_type` guidano API e chat-ui.

**Google Workspace MCP** (Gmail, Drive, Calendar, …), **GitHub Copilot MCP** e **Microsoft SharePoint / OneDrive** (Agent 365) richiedono `client_credentials_required: true` nel blocco `oauth:` — l’admin-ui mostra avviso, redirect URI e link a `setup_doc_url` / `admin_setup_hint` dal catalogo.

Per SharePoint/OneDrive gli endpoint Entra usano `{tenant_id}` nel catalogo; al runtime viene sostituito con il GUID estratto dall’`remote_url` installato (`…/tenants/{guid}/servers/…`).

Campi aggiuntivi utili:

- `remote_url_template: true` — URL con placeholder (es. `{tenant_id}`) da completare prima dell'install;
- `mcp_name_hints` — associa un nome nel registry (`clickup-mcp-server`) all'`id` catalogo.

L'elenco connettori curati è in [`config_std/mcp_connector_catalog.yaml`](../../config_std/mcp_connector_catalog.yaml) (source of truth).

Installazione: `POST /admin/mcp/install-from-catalog?connector_id=...` oppure pulsante **Install** in Hub.
Validazione pre-install: `POST /admin/mcp/probe-remote` con `{ "url": "..." }`.
MCP remoto personalizzato: `POST /admin/market/install-remote` (modal **Remote** in Hub).

## API

| Metodo | Path | Ruolo |
|--------|------|--------|
| GET | `/admin/mcp/connector-catalog` | JSON del catalogo (Bearer admin) |

Implementazione: [`src/mcp_connector_catalog.py`](../../src/mcp_connector_catalog.py), route in [`src/api/admin.py`](../../src/api/admin.py).

## UI e policy DB

[`admin-ui/app/hub/page.tsx`](../../admin-ui/app/hub/page.tsx): **Connettori consigliati**, installazione marketplace e, nel modal *Modifica configurazione*, sezione **Disponibilità utenti** (`credential_mode`, schema da catalogo, env suggerito).

Flusso: catalogo → registry (`aion_connector_id`) → sync [`mcp_server_configs`](user-isolation-and-credentials.md#hub-unificato-admin) → chat-ui per `per_user`.

Script: `scripts/sync_mcp_integration_from_catalog.py` (non modifica `env` registry senza `--apply-registry-env`).

## Integrità e disinstallazione

- **Disinstallazione** (`DELETE /admin/mcp/{slug}`): rimuove registry, policy DB, artefatti marketplace e **credenziali/preferenze utente** associate allo slug.
- **Controllo integrità**: `GET /admin/mcp/integrity` — credenziali orfane, policy stale, env non allineato allo schema, credenziali migrabili dopo reinstall (stesso `aion_connector_id`).
- **Riparazione**: `POST /admin/mcp/integrity/repair-all` o singolo `POST /admin/mcp/integrity/repair` con `{ "issue": {...} }`.
- Alla sync registry, se lo stesso `aion_connector_id` ha credenziali su uno slug orfano, vengono migrate automaticamente al nuovo slug.
- Lo schema credenziali in API include `env_placeholder` e `suggested_env_yaml` per copy/paste nel registry YAML.

Implementazione: [`src/runtime/mcp_integration_integrity.py`](../../src/runtime/mcp_integration_integrity.py).

## Grafici di sessione (stesso epic prodotto)

I tipi di grafico (`chart_kind`) e la variabile `AION_CHART_KIND_ENABLED` sono documentati in **[`docs/api-and-runtime/session-charts.md`](../api-and-runtime/session-charts.md)**.
