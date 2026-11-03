---
sidebar_position: 6
title: Server MCP remoti tramite mcp-remote (remote-bridge)
description: Come AION raggiunge server MCP streamable HTTP con Bearer token attraverso il ponte stdio mcp-remote - credenziali org_shared e per_user, broker in HTTP, versione fissata, ambiente ridotto e dimensionamento.
---

# Server MCP remoti tramite `mcp-remote` (`remote-bridge`)

Un server MCP remoto (streamable HTTP o SSE) si installa come voce `type: remote-bridge`. AION non
apre direttamente la connessione HTTP: avvia il ponte [`mcp-remote`](https://www.npmjs.com/package/mcp-remote),
che per AION è un normale server stdio e inoltra le richieste al server remoto con l'header
`Authorization`.

È il modo in cui AION SRE collega i propri broker (un container per fonte dati, tool in sola
lettura, Bearer token).

## Voce del registro

L'installazione da URL dell'admin (`build_remote_bridge_registry_config` in
`src/mcp_remote_install.py`) produce una voce simile:

```yaml
ssh_broker:
  type: remote-bridge
  command: node
  args:
    - node_modules/mcp-remote/dist/proxy.js
    - http://ssh-broker:8080/mcp
    - --header
    - "Authorization: Bearer ${API_KEY}"
  env:
    API_KEY: ${API_KEY}
  auth_env_var: API_KEY
  remote_url: http://ssh-broker:8080/mcp
  allow_http: true          # solo per broker in HTTP sulla rete interna
  enabled_tools: [read_status, search_logs]
```

`${API_KEY}` nell'header viene risolto da `mcp-remote` nel proprio ambiente: il token non compare
negli argomenti del processo.

## Credenziali

| `credential_mode` | Token | Variabile (`auth_env_var`) |
| --- | --- | --- |
| `org_shared` | Unico per l'organizzazione, cifrato nel `credential_store` | `API_KEY` / `OAUTH_TOKEN` / `BASIC_AUTH` |
| `per_user` | Uno per utente, collegato da chat-ui | `AION_USER_<SLUG>__<CHIAVE>` |

I broker di AION SRE usano `org_shared`: un token per AION, non uno per utente.

Se il token manca AION non avvia il ponte (`_remote_bridge_auth_missing` in `src/mcp_manager.py`).
Senza Bearer `mcp-remote` tenterebbe il proprio flusso OAuth nel browser. Con un token sbagliato un
broker che risponde `401` a tutte le richieste, compresa la registrazione del client OAuth, fa
terminare `mcp-remote` subito (meno di un secondo), senza callback in attesa.

:::note Voci `org_shared` installate prima della correzione
Fino alla versione che ha introdotto questa pagina, le voci `org_shared` avevano
`auth_env_var: AION_USER_<SLUG>__…` mentre il token arrivava in `API_KEY`, e il ponte non partiva
mai. `resolve_remote_bridge_auth_env_var` ora usa la variabile dell'header in questo caso, quindi
le voci esistenti funzionano senza modifiche.
:::

## Broker in HTTP: `allow_http`

`mcp-remote` rifiuta gli URL `http://` che non puntano a localhost. Per un broker raggiunto in HTTP
sulla rete Docker interna impostare `allow_http: true` sulla voce (solo da YAML,
`config/mcp_registry.local.yaml`). AION aggiunge `--allow-http` al momento dell'avvio
(`resolve_remote_bridge_spawn`), senza scriverlo negli `args` salvati.

Il traffico in chiaro è accettabile solo su una rete privata non condivisa; altrimenti esporre il
broker in HTTPS.

## Quali tool vede l'agente

Il filtro è `enabled_tools` sulla voce del registro (admin `POST /admin/mcp/{name}/tools-config`),
in aggiunta ai tool in sola lettura esposti dal broker. AION non usa l'opzione `--ignore-tool` di
`mcp-remote`.

## Versione di `mcp-remote`

Tutto il traffico verso i server remoti passa dal ponte, quindi la versione è fissata:

- `MCP_REMOTE_VERSION` in `src/mcp_remote_install.py`;
- `docker/package.mcp-remote.json` (versione esatta) e `docker/package-lock.mcp-remote.json`,
  installati nell'immagine backend con `npm ci --omit=dev`;
- fuori da Docker, senza `node_modules/mcp-remote` locale, AION avvia
  `npx -y mcp-remote@<MCP_REMOTE_VERSION>`.

Per aggiornarla: cambiare la versione nella costante e nel `package.mcp-remote.json`, rigenerare il
lockfile (`npm install --package-lock-only` in una cartella con quel `package.json`) e lanciare
`src/test/test_mcp_remote_install.py` (controlla che le tre versioni coincidano) e
`src/test/test_mcp_remote_bridge_broker.py`.

## Ambiente del processo

Il ponte è un server di terze parti: riceve solo `PATH`, `HOME`, locale, proxy e certificati
(`NODE_EXTRA_CA_CERTS`, …) più il blocco `env:` del registro, cioè il token. Nessuna variabile
`AION_*` del backend, tranne quelle di contesto (`AION_CURRENT_*`, `AION_CHAT_SESSION_ID`). Vedi
`AION_MCP_ENV_SCRUB` e `AION_MCP_ENV_ALLOWLIST` in
[isolamento per utente e credential store](user-isolation-and-credentials.md).

## Dimensionamento

Misura su un broker FastMCP locale (macOS, Node 22, `mcp-remote` 0.1.49): circa **100 MB di RSS**
per processo, invariati dopo 20 chiamate.

Quanti processi ci sono dipende dal pool (`AION_MCP_POOL=1`):

| Configurazione | Processi `mcp-remote` | Chiusura degli inattivi |
| --- | --- | --- |
| `AION_MCP_USER_POOL=1` (default) | uno per **utente** e per broker, condiviso da tutte le sue conversazioni | solo con `AION_MCP_USER_POOL_IDLE_CLEANUP=1`, dopo `AION_MCP_POOL_IDLE_SEC` |
| `AION_MCP_USER_POOL=0` | uno per **conversazione** e per broker | dopo `AION_MCP_POOL_IDLE_SEC` (default 1800 s, controllo ogni 60 s) |

Con il default, tutte le indagini di `sre-bot` condividono un solo processo per broker
(memoria ≈ broker × 100 MB) e il worker serializza le chiamate: con molte indagini contemporanee le
chiamate allo stesso broker si mettono in fila. Con `AION_MCP_USER_POOL=0` le chiamate vanno in
parallelo, ma i processi diventano indagini contemporanee × broker; il limite di concorrenza di
AION SRE li tiene sotto controllo.

## Test

`src/test/test_mcp_remote_bridge_broker.py` (marcatore `integration`) avvia un broker FastMCP
streamable HTTP con controllo del Bearer e lo raggiunge con `mcp-remote` reale: token giusto, token
mancante, token sbagliato e broker in HTTP su un IP non loopback con e senza `allow_http`. Viene
saltato se mancano `node` o `mcp-remote` locale; per indicarne uno installato altrove:

```bash
AION_TEST_MCP_REMOTE_PROXY=/percorso/node_modules/mcp-remote/dist/proxy.js \
  python -m pytest src/test/test_mcp_remote_bridge_broker.py -v
```
