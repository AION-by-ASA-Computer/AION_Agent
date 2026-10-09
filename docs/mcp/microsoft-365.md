---
sidebar_position: 5
title: Microsoft 365 (Softeria)
description: Connettore Graph per posta, calendario, file e attività, con app Entra e token per utente.
---

# Microsoft 365 (Softeria)

Il connettore `ms365` avvia [`@softeria/ms-365-mcp-server`](https://github.com/softeria/ms-365-mcp-server) come processo stdio (`npx`). Copre Outlook (posta e calendario), OneDrive, contatti e To Do tramite Microsoft Graph.

È un prodotto diverso dai connettori **Microsoft SharePoint** e **Microsoft OneDrive** già in catalogo. Quelli sono endpoint remoti Agent 365 (`agent365.svc.cloud.microsoft`) e restano dove sono. `ms365` è il server Softeria, locale al backend AION.

## Perché serve un'app Entra

Il server Softeria, da solo, fa login con **device code** e salva i token nel portachiavi del sistema operativo del processo. In AION quel processo è condiviso da tutti gli utenti del backend: un login da terminale collegherebbe un solo account Microsoft a tutta l'istanza.

AION quindi non usa quel login. Ottiene lui un token Graph **per utente** (stesso flusso OAuth della chat) e lo passa al processo nella variabile `MS365_MCP_OAUTH_TOKEN` (metodo BYOT del server). Il refresh lo fa AION, perché il server non rinnova un token ricevuto già pronto.

L'app pubblicata da Softeria non ha il redirect di AION. Va registrata un'app Entra propria e vanno incollati client id e client secret nel MCP Hub. Senza quei due valori il pulsante Accedi in chat non può completare il login.

## Cosa è già predisposto

L'installazione dal catalogo (`id: ms365`) registra questo avvio:

```text
npx -y @softeria/ms-365-mcp-server --org-mode --read-only --preset mail,calendar,files,tasks
```

- **Sola lettura.** Inviare mail, creare eventi o modificare file è disattivato finché non togli `--read-only` (vedi sotto).
- **`--org-mode`.** Senza questo flag il server espone solo gli strumenti degli account personali. Con il flag restano disponibili anche gli strumenti work/school (Teams e SharePoint non sono nel preset di default).
- **Preset** `mail`, `calendar`, `files`, `tasks`. Il server ha centinaia di tool: il preset tiene il contesto dell'agente su posta, calendario, file e attività.
- **Token.** L'env del registry è `MS365_MCP_OAUTH_TOKEN=${AION_USER_MS365__OAUTH_TOKEN}`. Lo slug installato deve restare `ms365`, altrimenti il placeholder non trova la credenziale.
- **Scope Graph** già nel catalogo: `offline_access`, `openid`, `profile`, `User.Read`, `Mail.Read`, `Calendars.Read`, `Contacts.Read`, `Files.Read`, `Tasks.Read`.
- **Tenant `common`.** Funziona per molti account aziendali. Gli account personali hanno un'eccezione, descritta sotto.

Il backend Docker include Node.js. In sviluppo locale (`uvicorn` sulla macchina) serve Node.js 20 o superiore, perché il server parte con `npx`.

## 1. Registrare l'app in Entra

1. Apri [Microsoft Entra admin center](https://entra.microsoft.com) → **Identity** → **Applications** → **App registrations** → **New registration**.
2. Nome, ad esempio `AION Microsoft 365`.
3. **Supported account types**, allineato al tenant che userai negli URL OAuth:
   - tenant `common`: *Accounts in any organizational directory and personal Microsoft accounts*;
   - tenant `consumers`: solo account personali Microsoft;
   - un GUID di directory: *Accounts in this organizational directory only*.
4. **Redirect URI**: piattaforma **Web** (non "Mobile and desktop"). L'URI deve coincidere con quello che AION invia al login.

| Dove gira AION | Redirect URI |
| --- | --- |
| API in locale, porta 8001 | `http://localhost:8001/v1/integrations/oauth/callback` |
| Docker con Caddy (`https://DOMINIO`) | `https://DOMINIO/api/v1/integrations/oauth/callback` |

Caddy toglie il prefisso `/api` prima di inoltrare al backend. Il redirect pubblico tiene `/api`; il path interno è `/v1/integrations/oauth/callback`.

5. **Certificates & secrets** → **New client secret**. Copia il valore subito: il portale non lo mostra di nuovo.
6. **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated** (non Application). Aggiungi gli stessi scope del catalogo: `offline_access`, `openid`, `profile`, `User.Read`, `Mail.Read`, `Calendars.Read`, `Contacts.Read`, `Files.Read`, `Tasks.Read`.
7. Su un tenant aziendale, **Grant admin consent**. Se il tenant vieta il consenso utente, senza questo passo il login fallisce per tutti.
8. Dalla pagina **Overview** copia **Application (client) ID**. Il **Directory (tenant) ID** serve solo se abbandoni `common`.

Non committare il secret. Vive solo nella configurazione OAuth del server MCP, nel database.

## 2. Installare il connettore

In **Admin → MCP Hub**, nella lista dei connettori consigliati, installa **Microsoft 365** (`POST /admin/mcp/install-from-catalog?connector_id=ms365`).

Poi, nella configurazione OAuth di quel server:

- **Client ID**: Application (client) ID dell'app Entra.
- **Client secret**: il secret appena creato.

Gli endpoint sono già impostati su `https://login.microsoftonline.com/common/oauth2/v2.0/authorize` e `.../token`. Cambiali solo se cambi tenant (passo 4).

Aggiungi `ms365` ai profili che devono usarlo (`mcp_servers` nel YAML del profilo, oppure la UI profili).

## 3. Collegare l'utente

Ogni persona apre **chat-ui → integrazioni** e sceglie **Accedi** su Microsoft 365. Il token resta sulla sua riga credenziali, non in un file condiviso.

La sessione MCP è in cache: dopo il primo collegamento avvia una chat nuova, così il processo parte con il token.

## Account personali e tenant `consumers`

Da giugno 2026 i refresh token emessi sull'authority `common` per gli account personali (`@outlook.com`, `@hotmail.com`, `@live.com`) vengono rifiutati al primo rinnovo. La sessione muore dopo circa un'ora.

Per quegli account:

1. Nell'app Entra, account supportati = solo personali, se non ti serve anche il lavoro.
2. Nel Hub, sostituisci `common` con `consumers` in authorization endpoint e token URL.
3. Nel registry del server (`config/mcp_registry.local.yaml`, voce `ms365`), imposta `MS365_MCP_TENANT_ID: "consumers"`.

Per una sola azienda, usa il GUID della directory al posto di `common` negli stessi tre punti, e limita l'app a quel tenant.

## Scrittura, Teams, altri preset

Il default è volutamente stretto. Per allargarlo modifica gli args nel registry e, se aggiungi permessi, anche gli scope OAuth nel Hub. L'utente deve rifare Accedi dopo un cambio di scope.

| Obiettivo | Args da aggiungere o togliere | Scope Graph delegati in più |
| --- | --- | --- |
| Inviare e modificare posta, eventi, file, attività | togli `--read-only` | `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`, `Files.ReadWrite`, `Tasks.ReadWrite` |
| Solo Outlook (niente file) | `--preset outlook` al posto della lista | togli `Files.Read` e `Tasks.Read` se non servono |
| Teams in lettura | tieni `--org-mode`, preset `teams` | `Chat.Read`, `ChannelMessage.Read.All`, `Team.ReadBasic.All`, `Channel.ReadBasic.All` |
| Meno token nel contesto | aggiungi `--discovery` | nessuno |

I nomi esatti dei preset sono quelli del server: `mail`, `calendar`, `files`, `personal`, `work`, `excel`, `contacts`, `tasks`, `onenote`, `search`, `users`, `outlook`, `onedrive`, `teams`, `teams-write`, `all`. Elenco aggiornato: `npx -y @softeria/ms-365-mcp-server --list-presets`.

`--read-only` e il preset non sostituiscono i permessi Entra. Un tool di scrittura con un token di sola lettura fallisce su Graph anche se togli il flag.

## Cosa non configurare

- **`npx @softeria/ms-365-mcp-server --login`** sul server AION. Scrive il token nel portachiavi dell'utente di sistema, visibile a tutte le chat.
- **Tool `login` / `verify-login`** del server come sostituto del pulsante Accedi. Stesso archivio condiviso.
- **Modalità `--http`** di Softeria dietro Caddy, salvo un deployment separato. AION parla già con il processo in stdio e non deve esporre la porta 3000 del server.
- Le variabili `MS365_MCP_CLIENT_ID` e `MS365_MCP_CLIENT_SECRET` nel processo. Con il token passato da AION il processo non fa il proprio login. Client id e secret stanno nella config OAuth del Hub.

## Verifica

1. Nel Hub, **Test** sul server `ms365` con lo stesso utente che ha fatto Accedi in chat. Il probe usa quel token; un admin che non ha collegato Microsoft riceve un errore di autenticazione, non un token finto.
2. In una chat del profilo che include `ms365`, chiedi la posta recente o gli eventi di oggi. Il primo avvio scarica il pacchetto npm e può richiedere qualche secondo.
3. Se Graph risponde `Insufficient privileges` o `403`, lo scope non è nel token: aggiungilo all'app, al Hub, e ripeti Accedi.
4. Se il redirect viene rifiutato (`AADSTS50011`), l'URI nel portale non è identico a quello della tabella sopra, compresi `http`/`https` e il prefisso `/api`.
