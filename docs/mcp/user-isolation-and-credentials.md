---
sidebar_position: 3
title: MCP isolamento per utente e credential store
description: HOME/XDG per processo MCP, credenziali cifrate per utente, placeholder AION_USER e flussi admin/chat.
---

# MCP: isolamento per utente e credential store

In deployment multi-utente, i processi MCP non devono condividere la stessa `$HOME` del sistema né token globali in chiaro. AION combina:

1. **Isolamento HOME/XDG** — ogni worker stdio riceve directory dedicate sotto `data/users/<user_id>/mcp_home/` (variabili `HOME`, `XDG_*`, `USERPROFILE`, `APPDATA`).
2. **Credential store** — tabella `user_mcp_credentials` in `aion.db` con valori cifrati (AES-256-GCM) e risoluzione `${AION_USER_*}` nell’`env:` del registry al momento dello spawn.

## Variabili d’ambiente

| Variabile | Default | Ruolo |
|-----------|---------|--------|
| `AION_MCP_USER_HOME_ISOLATION` | `1` | Abilita directory HOME/XDG per utente per i processi MCP stdio. |
| `AION_MCP_USER_CREDENTIALS` | `0` | Abilita lettura/scrittura credenziali per-utente e API `/v1/integrations`. |
| `AION_CREDENTIAL_ENCRYPTION_KEY` | — | Chiave hex (32 byte = 64 caratteri) per AES-GCM. Obbligatoria in produzione se `AION_MCP_USER_CREDENTIALS=1`. |
| `AION_DEFAULT_TENANT_ID` | `default` | Tenant usato per le righe credenziali. |

Generazione chiave:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Placeholder nel registry (`env:`)

- `${VAR}` — risolto da `os.environ` / `.env` (comportamento storico).
- `${AION_USER_<SLUG_MAIUSCOLO>__<CHIAVE>}` — risolto dal DB per l’utente corrente, es. `${AION_USER_EMAIL_MCP__ACCESS_TOKEN}` per lo slug registry `email_mcp`.
- `${AION_USER_<CHIAVE>}` — forma breve: la chiave è relativa allo **slug del server** in cui compare la mappa `env`.

Vedi anche il commento di esempio in `config_std/mcp_registry.yaml`.

## Modalità credenziali (`credential_mode`)

Il campo `credential_mode` nella tabella `mcp_server_configs` definisce come vengono gestite le credenziali per ciascun server MCP. I valori possibili sono:

| Valore | Significato | Registry `env` | Credenziali |
|--------|------------|----------------|-------------|
| **`none`** | Nessuna credenziale richiesta. Il server funziona senza segreti o usa variabili globali non sensibili. | Placeholder `${VAR}` risolti da `os.environ` | Nessun form utente |
| **`org_shared`** | Credenziali condivise a livello di organizzazione. L'admin configura i valori in MCP Hub e vengono iniettati via `.env` del backend. | Placeholder `${VAR}` risolti da `os.environ` | Messaggio «Gestito dall'organizzazione» in chat-ui |
| **`per_user`** | Ogni utente configura le proprie credenziali personali nella chat-ui. I valori sono cifrati (AES-256-GCM) e isolati per `(user_id, tenant_id, server_slug, credential_key)`. | Placeholder `${AION_USER_*}` risolti dal credential store per-utente | Form credenziali in chat-ui → `/integrations` |

L'inferenza automatica della modalità avviene in `src/mcp_integration_sync.py` analizzando i placeholder nelle variabili d'ambiente del registry:
- `${AION_USER_*}` → `per_user`
- `${VAR}` (variabili standard) → `org_shared`
- Nessuna variabile → `none`

## Hub unificato (admin)

La configurazione admin avviene in **un solo percorso**: **MCP Hub** (`/hub` → Modifica configurazione). Vedi [MCP Hub Wizard](hub-wizard.md) per il flusso completo.

| `credential_mode` | Admin in Hub | Registry `env` | Chat-ui |
|-------------------|--------------|----------------|---------|
| `none` | Nessun segreto | Solo env non sensibili | Nessun form |
| `org_shared` | Form credenziali catalogo | `${VAR}` globali | Messaggio «gestito dall'organizzazione» |
| `per_user` | Anteprima campi + «Applica env suggerito» | `${AION_USER_*}` | Form credenziali utente |

Lo **schema credenziali** è rilevato automaticamente (README / `.env.example` / sorgenti) al wizard e alla preview; il catalogo opzionale `config/mcp_connector_catalog.yaml` arricchisce solo integrazioni curate.

API aggiuntive: `POST /admin/mcp-integrations/sync-from-registry`, `GET .../preview`, `POST .../advise`, `POST .../apply-suggested-env`.

Migrazione installazioni esistenti:

```bash
alembic upgrade head
./.venv/bin/python scripts/sync_mcp_integration_from_catalog.py
```

La pagina `/integrations` in admin-ui reindirizza a `/hub?focus=integrations`.

Profilo consulente: `mcp_integration_advisor` (chat-ui `?profile=mcp_integration_advisor&context=<slug>`).

## Modello dati

- **`mcp_server_configs`** — policy chat (`credential_mode`, `is_enabled_for_users`, schema dal catalogo, `aion_connector_id`).
- **`user_mcp_credentials`** — una riga per `(user_id, tenant_id, server_slug, credential_key)` con `value_encrypted`.

## API

- **Admin** (Bearer admin): `GET/POST/PATCH/DELETE /admin/mcp-integrations` — gestione catalogo integrazioni.
- **Chat** (Bearer token chat o secret BFF dove applicabile): `GET /v1/integrations`, `POST /v1/integrations/credentials`, `DELETE /v1/integrations/credentials/{slug}/{key}`.  
  Autenticazione: **non** usano `X-API-Key` delle API v1 “SDK”; usano lo stesso modello degli altri endpoint user-facing protetti da `require_chat_auth`. Con `AION_CHAT_PASSWORD_AUTH=0`, la lista è anonima senza hint credenziali; **mutazioni** (salvataggio credenziali) richiedono identità non anonima.

## UI

- **Admin UI** — **MCP Hub** (`/hub`): installazione, env registry, policy utenti e modalità credenziali. Voce «Policy MCP (Hub)» per il focus integrazioni.
- **Chat UI** — «Le mie integrazioni» (`/integrations`): form solo per `credential_mode=per_user`; `org_shared` mostra messaggio senza input.

## Operazioni

Dopo le migration Alembic, seed idempotente del catalogo da registry:

```bash
./.venv/bin/python scripts/seed_mcp_integration_configs.py
```

Lo script `scripts/upgrade-aion.sh` / `upgrade_core.py` invoca il seed in modo non bloccante dopo `init_unified_db`.

## OAuth

L’endpoint `POST /v1/integrations/oauth/callback` è estensibile; al momento restituisce `501` finché non viene implementato lo scambio codice/token per i provider specifici. Le credenziali manuali (testo/password) sono supportate.

## Backup

La perdita di `AION_CREDENTIAL_ENCRYPTION_KEY` rende irreversibili i valori cifrati: conservare la chiave in un vault aziendale insieme ai backup di `aion.db`.

## Esempio end-to-end: email (IMAP/SMTP)

Template in `config_std/`; runtime legge `config/` (vedi `scripts/sync_config.py`).

1. **Registry** (`config/mcp_registry.local.yaml`): server `email-mcp-server` con `command: bun`, `args: [run, mcp_servers/email-mcp-server/index.ts]`, `aion_connector_id: email_imap`, env con `${AION_USER_EMAIL_MCP_SERVER__*}`.
2. **Profilo** (`config/profiles/generic_assistant.yaml`): includere `email-mcp-server` in `mcp_servers` e skill `email_imap_mcp`.
3. **Hub**: wizard AI o Modifica → `credential_mode=per_user` → Applica env suggerito → abilita chat. **Probe** (`POST /admin/mcp/{slug}/probe`) per verificare `search_emails`, `send_email`, `list_folders`.
4. **Chat-ui**: Le mie integrazioni → compilare `EMAIL_USER`, `EMAIL_PASSWORD`, `IMAP_*`, `SMTP_*`.
5. **Env**: `AION_MCP_USER_CREDENTIALS=1` e `AION_CREDENTIAL_ENCRYPTION_KEY` nel `.env` backend.

Migrazione chiavi legacy (`IMAP_USER` → `EMAIL_USER`):

```bash
./.venv/bin/python scripts/migrate_email_credential_keys.py --slug email-mcp-server --dry-run
```

## Architettura unificata (pipeline)

Unica funzione `apply_integration_config` in `src/mcp_integration_sync.py` usata da:

- Wizard commit (`POST /admin/mcp/install-wizard/commit`)
- Applica env (`POST /admin/mcp-integrations/{slug}/apply-suggested-env`)
- Post-install marketplace (`normalize_and_apply_env_after_install`)

Discovery + registry definiscono schema/env; il DB (`mcp_server_configs`) la policy; le skill guidano l'agente su **quando** usare i tool (non mapping prompt in Python).
