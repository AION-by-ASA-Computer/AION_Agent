---
sidebar_position: 2
title: Catalogo connettori MCP consigliati
description: YAML curato, endpoint admin, MCP Hub e checklist QA / sicurezza per integrazioni aziendali.
---

# Catalogo connettori MCP consigliati

AION modella la **connettività enterprise** tramite **server MCP** (registry + marketplace in Admin). Lo **schema credenziali** per server arbitrari è rilevato automaticamente da README, `.env.example` e sorgenti ([`src/mcp_credential_discovery.py`](../../src/mcp_credential_discovery.py)).

Il file opzionale **`config/mcp_connector_catalog.yaml`** può elencare integrazioni curate (Gmail, ClickUp, …) con:

- descrizione e categoria;
- link alla documentazione del vendor o allo standard MCP;
- **`registry_search_hint`**: stringa usata dal pulsante «Cerca nel marketplace» nella pagina **Admin → MCP Hub**;
- **`example_registry_block`**: snippet commentato da copiare in `config/mcp_registry.local.yaml` dopo audit del pacchetto scelto;
- **`required_env` / `optional_env`**: solo **nomi** variabili (mai segreti in git).
- **`runtime_env_aliases`** (opzionale): mappa **nomi env attesi dal processo MCP** verso **chiavi alternative** (es. snippet da Claude Code / altri client). All’avvio stdio, se la chiave destinazione è vuota e una sorgente è valorizzata, viene copiato il valore — tutto dichiarativo nel YAML, senza codice per connettore.

## Override locale

**`config/mcp_connector_catalog.yaml`** (stessa struttura `version` + `connectors`) è opzionale: se assente, l’endpoint restituisce catalogo vuoto e Hub/wizard usano solo discovery + LLM.

## API

| Metodo | Path | Ruolo |
|--------|------|--------|
| GET | `/admin/mcp/connector-catalog` | JSON del catalogo (Bearer admin) |

Implementazione: [`src/mcp_connector_catalog.py`](../../src/mcp_connector_catalog.py), route in [`src/api/admin.py`](../../src/api/admin.py).

## UI e policy DB

[`admin-ui/app/hub/page.tsx`](../../admin-ui/app/hub/page.tsx): **Connettori consigliati**, installazione marketplace e, nel modal *Modifica configurazione*, sezione **Disponibilità utenti** (`credential_mode`, schema da catalogo, env suggerito).

Flusso: catalogo → registry (`aion_connector_id`) → sync [`mcp_server_configs`](user-isolation-and-credentials.md#hub-unificato-admin) → chat-ui per `per_user`.

Script: `scripts/sync_mcp_integration_from_catalog.py` (non modifica `env` registry senza `--apply-registry-env`).

## Grafici di sessione (stesso epic prodotto)

I tipi di grafico (`chart_kind`) e la variabile `AION_CHART_KIND_ENABLED` sono documentati in **[`docs/api-and-runtime/session-charts.md`](../api-and-runtime/session-charts.md)**.
