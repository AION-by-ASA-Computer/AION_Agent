---
sidebar_position: 4
title: MCP Hub — Wizard di installazione e configurazione
description: Flusso guidato per installare MCP server da marketplace, far analizzare i requisiti all’AI advisor, definire org_shared vs per_user e distribuire le policy.
---

# MCP Hub: wizard di installazione e configurazione

Il **MCP Hub** (`/hub` in Admin UI) è il punto centrale per gli amministratori per gestire l'intero ciclo di vita dei server MCP nell'organizzazione AION.

## Architettura del wizard

Il wizard guida l'admin attraverso **4 fasi**:

```
┌──────────────┐    ┌──────────────────┐    ┌──────────────┐    ┌──────────────────┐
│ 1. Install   │ → │ 2. AI Analysis   │ → │ 3. Admin       │ → │ 4. Confirm &      │
│    (market)  │    │    (advisor)     │    │    Review      │    │    Distribute     │
└──────────────┘    └──────────────────┘    └──────────────┘    └──────────────────┘
```

## Fase 1: Selezione e installazione

L'admin accede a **MCP Hub → tab Marketplace** e:

1. Cerca un server MCP per nome o parola chiave (es. "clickup", "email", "github")
2. Clicca su **WIZARD** (installazione guidata + analisi AI) oppure **INSTALL** (solo clone/registry)
3. Il sistema esegue l'installazione tramite `mcp_installer.py` (supporta `npx`, `git clone`, `binary download`)
4. Dopo l'installazione, il server appare nella lista del registry MCP (tab **Installati**)

Gli id marketplace (`github:owner/repo`, `glama:owner/repo`, `npx:package`) vengono risolti **localmente** al momento dell'installazione: non serve che la voce sia ancora presente nei risultati di ricerca. Per repository GitHub non indicizzati, usa **Installa da URL GitHub** (`POST /admin/market/install-github`).

**Endpoint coinvolti:** `POST /admin/mcp/install-wizard/start` (con `market_item_id` o `server_slug`)

## Fase 2: Analisi AI automatica

Appena completata l'installazione, il sistema esegue automaticamente:

1. **Discovery automatica** ([`mcp_credential_discovery.py`](../../src/mcp_credential_discovery.py)): README, `.env.example`, sorgenti, env registry
2. **Catalogo opzionale** (`config/mcp_connector_catalog.yaml`) solo se presente entry curata
3. **Analisi delle variabili d'ambiente** nel registry per inferire la modalità credenziali:
   - Presenza di placeholder `${AION_USER_*}` → **`per_user`** (credenziali personali per ogni utente)
   - Presenza di placeholder `${VAR}` standard → **`org_shared`** (credenziali condivise dell'organizzazione)
   - Nessuna variabile sensibile → **`none`** (nessuna credenziale richiesta)
4. **Generazione dello schema** da discovery (+ catalogo opzionale)
5. **Suggerimento env** (`suggested_env_per_user` / `suggested_env_org_shared`) con placeholder `${AION_USER_*}`
6. **LLM advise** sui file reali del server; se propone `none` ma la discovery trova env di login → correzione automatica

**L'AI advisor** (`POST /admin/mcp-integrations/advise`) produce un report con:
- `credential_mode` consigliato (`none` | `org_shared` | `per_user`)
- `credential_schema`: lista dei campi richiesti (key, label, type, required)
- `suggested_env`: mappa delle variabili da aggiungere al registry
- `warnings`: eventuali avvertenze
- `steps_markdown`: checklist in linguaggio naturale

L'admin può anche avviare una **chat con il profilo `mcp_integration_advisor`** per un'analisi interattiva più approfondita.

## Fase 3: Revisione admin

Nella schermata di revisione, l'admin vede il risultato dell'analisi AI e può **modificare manualmente**:

| Campo | Descrizione |
|-------|-------------|
| **Modalità credenziali** | `none` / `org_shared` / `per_user` — dropdown selezionabile |
| **Schema credenziali** | Per ogni campo: key, label, tipo (text/password/oauth), obbligatorietà |
| **Disponibile in chat** | Abilita/disabilita il server per gli utenti (`is_enabled_for_users`) |
| **Gli utenti possono disabilitare** | Se attivo, gli utenti vedranno il toggle nella loro pagina integrazioni |
| **Applica env suggerito** | Checkbox: se spuntata, al commit le variabili vengono scritte nel registry |

Tutti i campi sono pre-compilati con i valori suggeriti dall'AI e possono essere sovrascritti.

## Fase 4: Riepilogo e distribuzione

L'ultima schermata mostra un **riepilogo** di tutte le scelte:

- Server slug e display name
- Modalità credenziali selezionata
- Numero di campi credenziali richiesti
- Stato di abilitazione per gli utenti
- Variabili d'ambiente che verranno scritte nel registry

L'admin clicca **"Completa installazione"** per confermare. Il sistema esegue atomicamente:

1. **Aggiornamento del registry** (`PATCH mcp_registry.local.yaml`) con le variabili d'ambiente
2. **Creazione/aggiornamento della policy** (`McpServerConfig` in `aion.db`) con modalità, schema, abilitazione
3. **Invalidazione della cache** agent in modo che i nuovi tool siano disponibili al prossimo avvio chat

**Endpoint coinvolti:** `POST /admin/mcp/install-wizard/commit`

## Dopo la distribuzione

### Per gli admin
- Il server appare nella lista **MCP Hub → Installati** con badge che indicano la modalità credenziali
- Possono modificare la policy in qualsiasi momento cliccando **"Modifica configurazione"**
- Possono **disabilitare** il server per tutti gli utenti o **eliminarlo** completamente

### Per gli utenti
- Se `credential_mode = per_user`: il server appare in **chat-ui → Le mie integrazioni** con un form per inserire le credenziali personali
- Se `credential_mode = org_shared`: appare con messaggio "Gestito dall'organizzazione — nessuna configurazione personale richiesta"
- Se `user_may_disable = true`: gli utenti possono disabilitare il server individualmente dal toggle nella card
- Un'icona **⚠ gialla** appare nell'area di input chat se ci sono integrazioni con credenziali mancanti

### Per i profili agente
- L'admin deve aggiungere lo `slug` del server ai profili che devono usarlo (in `config/profiles/*.yaml`, campo `mcp_servers`)
- Il profilo `mcp_integration_advisor` può essere usato per assistenza nella configurazione

## Variabili d'ambiente per il wizard

Il wizard usa queste variabili lato backend:

```bash
# Abilita il credential store per-utente (necessario per per_user)
AION_MCP_USER_CREDENTIALS=1

# Chiave di cifratura AES-256 (64 caratteri hex)
AION_CREDENTIAL_ENCRYPTION_KEY=<generata con secrets.token_hex(32)>

# Isolamento HOME per i processi MCP
AION_MCP_USER_HOME_ISOLATION=1
```

## Risoluzione problemi

| Problema | Causa probabile | Soluzione |
|----------|----------------|-----------|
| Il server non appare in chat-ui dopo l'installazione | `is_enabled_for_users` non attivo | Abilitare il toggle in MCP Hub |
| Le credenziali non vengono salvate | `AION_MCP_USER_CREDENTIALS=0` | Impostare `AION_MCP_USER_CREDENTIALS=1` e riavviare backend |
| Errore "Integration not found" nel wizard | Slug non presente nel registry | Verificare che l'installazione marketplace sia completata |
| «Voce marketplace non trovata» con id `github:…` | Versione backend senza risoluzione locale degli id GitHub | Aggiornare backend: `_find_marketplace_item` costruisce il payload da `github:owner/repo` senza nuova ricerca; in alternativa **Installa da URL GitHub** |
| Messaggio errore JSON grezzo nel wizard | Risposta FastAPI non parsata in UI | Admin UI usa `readApiErrorMessage` su `detail` — aggiornare `admin-ui` se vedi ancora `{"detail":…}` |
| L'AI advisor propone `none` ma il server ha env | README enfatizza solo config.toml | La discovery corregge se trova `MCP_EMAIL_*` / simili; verificare install in `mcp_servers/<slug>` |

## Riferimenti

- **Admin UI:** `admin-ui/app/hub/page.tsx` (983 linee, componente principale)
- **Wizard component:** `admin-ui/components/McpInstallWizard.tsx` (172 linee)
- **Backend wizard API:** `src/api/admin.py` → `mcp_install_wizard_start()` / `mcp_install_wizard_commit()`
- **Sync logica:** `src/mcp_integration_sync.py` (335 linee, inferenza modalità e schema)
- **Discovery:** `src/mcp_credential_discovery.py` — **Catalogo opzionale:** `config/mcp_connector_catalog.yaml`
- **Profilo advisor:** `config_std/profiles/mcp_integration_advisor.yaml`
