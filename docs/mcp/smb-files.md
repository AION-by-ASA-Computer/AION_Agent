---
title: File server Windows (SMB)
sidebar_position: 7
description: Connettore MCP smb_files — l'agente legge e scrive i file delle share SMB del file server Windows con le credenziali del singolo utente (ACL NTFS rispettate). Architettura, setup admin e utente, rete, blocco account, sicurezza.
---

# File server Windows (SMB)

Il connettore **`smb_files`** permette all'agente AION di leggere e scrivere i file dei
Windows Server aziendali (share SMB sulla LAN) **con le credenziali Windows del singolo
utente**. Il file server applica quindi le **ACL NTFS** dell'utente e il suo audit
mostra la persona reale, non un account di servizio condiviso.

| Chi | Cosa fa | Dove | Quante volte |
|-----|---------|------|--------------|
| Admin | Indica server, share consentite e limiti; abilita il connettore | admin-ui → Impostazioni → **File server** + **MCP Hub** | Una volta |
| Utente | Inserisce `DOMINIO\utente` e password Windows | chat-ui → **Le mie integrazioni** | Una volta (e a ogni cambio password) |
| Utente | Chiede all'agente di cercare, leggere o salvare file | chat | Sempre |

## Perché è fatto così

- **Credenziali per utente, non di servizio.** Un account unico con accesso a tutto
  aggirerebbe le ACL NTFS e renderebbe l'audit inutile: l'agente vedrebbe i file di tutti
  a chiunque lo interroghi. Con le credenziali dell'utente l'agente non può mai fare più
  di quanto l'utente possa già fare da Esplora risorse.
- **Server e share decisi dall'admin.** L'utente non sceglie a cosa connettersi: l'agente
  raggiunge solo l'host configurato e solo le share in allowlist. Questo limita il danno
  di una prompt injection (un file che dice «leggi `\\altroserver\...`») e impedisce
  l'accesso alle share amministrative.
- **Nessuna cancellazione.** SMB non ha cestino: un errore dell'agente sarebbe
  irreversibile. Per questo il connettore espone solo lettura, creazione, aggiornamento
  esplicito e rinomina.

## Architettura

```
chat-ui (Le mie integrazioni)            admin-ui (Impostazioni → File server)
  SMB_USERNAME / SMB_PASSWORD              host, porta, dominio, share [+ sola lettura], limiti
        │ POST /v1/integrations/credentials        │ GET/PUT /admin/smb, POST /admin/smb/test
        ▼                                          ▼
 user_mcp_credentials (AES-256-GCM)         smb_settings (1 riga per tenant, nessun segreto)
        │ env allo spawn                           │ letta dal server MCP (cache TTL 30 s)
        └──────────────► mcp_servers_std/smb_files/server.py (FastMCP, sottile)
                               └─► src/tools/smb_files/* (logica testabile) ─► smbprotocol ─► \\server\share (TCP 445)
```

- **Credenziali utente**: riusano il [credential store per-utente](user-isolation-and-credentials.md).
  Il registry (`config_std/mcp_registry.yaml`) dichiara
  `SMB_USERNAME: ${AION_USER_SMB_FILES__SMB_USERNAME}` e analogo per la password; i
  valori sono risolti dal DB solo allo spawn del processo MCP dell'utente. Per questo
  `credential_mode` del connettore risulta `per_user`.
- **Configurazione admin**: tabella `smb_settings` (una riga per tenant, come le
  impostazioni SMTP). Il server MCP la legge per `AION_CURRENT_TENANT_ID` con una cache
  di 30 secondi: un salvataggio admin vale entro quel tempo, senza riavviare i worker.
- **Un worker per chat**: `smb_files` è in `_DEFAULT_SESSION_SCOPED_SERVERS`
  (`src/mcp_manager.py`) perché `smb_copy_to_session` e `smb_upload_from_session`
  usano la workspace della sessione di chat.
- **Connessione lazy**: il processo MCP viene avviato anche con credenziali vuote o
  mock (probe dell'Hub, utente che non ha ancora configurato nulla). Avvio e
  `list_tools` non fanno quindi I/O di rete; la connessione SMB si apre dentro il
  singolo tool, e lo schema dei tool non dipende dalle credenziali.

Codice: logica in `src/tools/smb_files/` (`paths`, `credentials`, `auth_guard`,
`client`, `extract`, `ops`, `probe`, `settings_store`), wrapper MCP in
`mcp_servers_std/smb_files/server.py`, API admin in `src/api/admin_smb.py`, UI in
`admin-ui/components/settings/SmbSection.tsx`.

## Tool esposti all'agente

| Tool | Tipo | Cosa fa |
|------|------|---------|
| `smb_list_shares` | lettura | Share consentite dall'admin e quali sono in sola lettura |
| `smb_list_dir` | lettura | Contenuto di una cartella |
| `smb_stat` | lettura | Tipo, dimensione, data di modifica |
| `smb_search` | lettura | Ricerca per nome (glob o sottostringa), limitata per profondità, risultati e tempo (20 s) |
| `smb_read_file` | lettura | Testo di PDF, DOCX, XLSX, CSV, TXT, MD, JSON, paginato a caratteri |
| `smb_copy_to_session` | lettura | Copia il file in `workspace/smb/` della sessione (per OCR o sandbox, es. PDF scansionati) |
| `smb_write_text` | scrittura | Crea un file di testo UTF-8 |
| `smb_upload_from_session` | scrittura | Carica un file dalla workspace di sessione |
| `smb_mkdir` | scrittura | Crea una cartella (anche intermedie) |
| `smb_move` | scrittura | Rinomina/sposta **nella stessa share** |

Regole comuni:

- I percorsi si scrivono `Share/sotto/cartella/file.ext` oppure in forma UNC
  `\\host\Share\...` (l'host deve essere esattamente quello configurato).
- Le scritture non sovrascrivono: se il file esiste l'errore è `already_exists`.
  `overwrite=True` richiede conferma esplicita dell'utente, come dichiarato nella
  descrizione dei tool. Le scritture falliscono su share «sola lettura».
- Spostare tra share diverse non è supportato (richiederebbe una cancellazione).
- Gli errori sono sempre JSON `{"ok": false, "error": "<codice>", "message": "..."}`,
  mai eccezioni. Codici principali: `credentials_missing`, `auth_failed`,
  `account_locked`, `password_expired`, `account_disabled`, `access_denied`,
  `not_found`, `already_exists`, `share_read_only`, `share_not_allowed`,
  `host_not_allowed`, `invalid_path`, `too_large`, `timeout`, `unreachable`,
  `not_configured`.
- I log di audit del server MCP riportano utente, operazione e percorso, **mai** i
  contenuti dei file né le password.

## Setup admin

### 1. Requisiti

Nel `.env` del backend: `AION_MCP_USER_CREDENTIALS=1` e `AION_CREDENTIAL_ENCRYPTION_KEY`
(vedi [credential store](user-isolation-and-credentials.md)).
`smbprotocol` è già in `requirements.txt`; non servono modifiche all'immagine Docker.

### 2. Configurare il file server (admin-ui)

**Impostazioni → File server**:

| Campo | Significato |
|-------|-------------|
| Host / Porta | Nome DNS o IP del file server (solo host, niente `\\` o `/`) e porta SMB (default 445) |
| Dominio predefinito | Usato quando l'utente scrive solo `mario.rossi`; con `utente@dominio` o `DOMINIO\utente` viene ignorato |
| Share | Allowlist di nomi share, ciascuna con etichetta e interruttore **sola lettura** |
| Protocollo di autenticazione | `ntlm` (default) o `negotiate` (predisposizione Kerberos, vedi sotto) |
| Richiedi cifratura SMB3 | Rifiuta server che non cifrano il traffico |
| Limiti lettura / scrittura (MB) | Dimensione massima per file (default 25 MB, max 500) |
| Durata blocco locale (minuti) | Vedi [Protezione dal blocco account](#protezione-dal-blocco-account) (default 30, min 5) |

Il salvataggio valida i dati: rifiuta share amministrative (`C$`, `ADMIN$`, `IPC$`, qualunque
nome che finisce con `$`), nomi con sotto-percorsi (l'allowlist è per share, non per cartella),
duplicati (i nomi share non distinguono maiuscole) e, con il connettore abilitato, richiede
host e almeno una share. Ogni salvataggio è registrato nell'audit (`smb.update`) e riflette
il flag «abilitato» sulla voce `smb_files` dell'Hub.

**Testa connessione** (`POST /admin/smb/test`):

- senza credenziali: connessione TCP + negoziazione SMB, verifica host, porta e dialetto;
- con utente e password inseriti per quel test: anche logon e accesso a **ogni** share,
  con esito per share. Le credenziali di test vivono solo nella richiesta: non vengono
  salvate, loggate né scritte nell'audit (solo `with_credentials`). Un tentativo errato
  conta ai fini del blocco account AD: usare un account di test.

Il test funziona anche a connettore disabilitato, così si verifica il server prima di accenderlo.

### 3. Abilitare il connettore

`smb_files` **non** è nei profili di default. In **MCP Hub** abilitarlo per gli utenti
e aggiungerlo a `mcp_servers:` dei profili che devono usarlo (es. `generic_assistant`).

## Setup utente

In chat-ui → **Le mie integrazioni → File server Windows (SMB)** l'utente inserisce:

- **Utente Windows**: `DOMINIO\mario.rossi`, `mario.rossi@azienda.local` oppure solo
  `mario.rossi` se l'admin ha impostato il dominio predefinito;
- **Password Windows**: campo **write-only**. Dopo il salvataggio compare solo `****` e
  non esiste modo di rileggerla (nemmeno con l'icona «occhio», che per questi campi è
  nascosta).

La password non va **mai** scritta in chat: il testo di una chat finisce in cronologia,
memoria e log. Alla prima richiesta senza credenziali l'agente risponde con
`credentials_missing` e rimanda l'utente a questa pagina.

Quando l'utente cambia password in Windows deve aggiornarla qui; il salvataggio riavvia i
worker MCP dell'utente (`restart_workers_for_user`) così la nuova password è subito attiva.

## Rete

- Il backend deve raggiungere il file server in **TCP 445** (SMB2/3; SMB1 non è
  supportato). Nessuna porta va esposta verso il browser: l'unico client SMB è il
  backend.
- Serve la risoluzione **DNS interna** dell'host configurato. Nel container backend il
  DNS è quello dell'host Docker: se non risolve i nomi del dominio aziendale, aggiungere
  al servizio `backend` di `docker-compose.yml` un `dns:` con il DNS aziendale; in
  alternativa un `extra_hosts:` con la coppia nome → IP, oppure indicare direttamente
  l'IP come host nell'admin-ui.
- Con più reti (VPN, VLAN) verificare con **Testa connessione** dal backend, non dal
  proprio PC: è il backend che apre la connessione.
- Per traffico cifrato attivare «Richiedi cifratura SMB3» (richiede dialetto 3.0+ lato
  server).

### Ambiente di sviluppo

`docker-compose.dev.yml` include un server Samba di test (profilo `smb`) con due utenti
(`alice`, `bob`) e due share (`Documenti` in lettura/scrittura, `Archivio` in sola lettura
riservata ad `alice`):

```bash
docker compose -f docker-compose.dev.yml --profile smb up samba
```

Dal backend nel compose l'host è `samba` porta 445; dalla macchina host (test, `smbclient`)
è `localhost:1445`. In admin-ui configurare host e share, poi **Testa connessione**
con `alice` / `alice-pass-dev`.

## Protezione dal blocco account

Active Directory blocca un account dopo poche password errate (tipicamente 5-10). Un
agente che ritenta in loop un tool fallito potrebbe bloccare l'account dell'utente
**anche per tutti gli altri servizi aziendali**. Per questo il connettore applica un
blocco locale (`auth_guard`):

1. al **primo** errore di logon (`auth_failed`, `account_locked`, `password_expired`,
   `account_disabled`) viene scritto un marker nella HOME isolata dell'utente
   (`data/users/<uid>/mcp_home/.smb_auth_block.json`, permessi 0600), quindi condiviso
   da tutte le chat aperte dello stesso utente;
2. il marker contiene un fingerprint HMAC di utente+password (salt casuale) e il
   motivo: **mai la password**;
3. finché le credenziali correnti hanno quel fingerprint, ogni tool risponde subito con
   lo stesso errore **senza contattare il server**;
4. se l'utente aggiorna le credenziali il fingerprint cambia e si riprova da sé;
5. per `account_locked` il blocco scade dopo la «durata blocco locale» configurata
   (il lockout server-side scade a sua volta); un logon riuscito rimuove il marker.

Inoltre le credenziali vuote o mock (probe dell'Hub, utente non configurato) sono
riconosciute **prima** di qualsiasi connessione: una password finta non deve mai
presentarsi al server come tentativo fallito.

## NTLM e Kerberos

- **v1: NTLM** (`auth_protocol=ntlm`, via `smbprotocol`). Zero configurazione: serve solo
  utente e password. Funziona anche con host indicati per IP.
- **Kerberos è predisposto ma non attivo**: l'impostazione `negotiate` esiste, ma il suo
  uso reale richiede librerie `krb5`/`gssapi` nell'immagine del backend, la
  configurazione del realm (`krb5.conf`), l'host indicato col **nome DNS** (non l'IP, per
  lo SPN) e orologi sincronizzati. È in roadmap: finché non è completato, il valore consigliato resta `ntlm`
  e `negotiate` può fallire con `auth_failed` se manca un meccanismo utilizzabile.
- NTLM può essere disabilitato per policy dai domain controller: in tal caso il test
  con credenziali lo evidenzia e l'unica strada sarà Kerberos.

## Sicurezza

| Rischio | Contromisura |
|---------|--------------|
| Lettura/scrittura oltre i permessi dell'utente | Credenziali per utente: il file server applica le ACL NTFS |
| Accesso a dischi o share di sistema | Allowlist per share; nomi `*$` rifiutati sia dall'admin-ui sia a runtime |
| Path traversal (`..`, segmenti con punto/spazio finale, caratteri non validi) | `paths.resolve_path`: validazione **prima** di ogni chiamata di rete |
| Host diverso da quello configurato (UNC arbitrario) | Rifiutato con `host_not_allowed` |
| Perdita irreversibile di dati | Nessun tool di cancellazione; niente overwrite senza flag esplicito; niente spostamenti tra share |
| Scritture accidentali su archivi | Share marcabili **sola lettura** dall'admin, applicato lato server MCP |
| File enormi che saturano memoria/contesto | Limiti di lettura e scrittura per file; lettura a pagine |
| Lettura della password salvata | Campo `write_only`: `GET /v1/integrations/credentials/{slug}/{key}` risponde 403 `secret_write_only` e la chat-ui non mostra mai il valore |
| Password nei log o nell'audit | Mai loggata; l'audit dell'admin test registra solo `with_credentials` |
| Blocco account AD da retry dell'agente | `auth_guard` (sezione precedente) |
| **Prompt injection dal contenuto dei file** | Il testo letto è dato non fidato: le descrizioni dei tool lo dichiarano e il server non esegue nulla. La contromisura strutturale è che l'agente non ha comunque più diritti dell'utente, nessuna cancellazione e nessuna share fuori allowlist. Per share con file di terzi è consigliabile marcarle in sola lettura |

### Da sapere

- Un utente può far scrivere all'agente ovunque **abbia** diritti di scrittura sulle share
  in allowlist non marcate in sola lettura: se un file letto contiene istruzioni ostili,
  l'impatto massimo è quello di un utente che sbaglia, ma senza cancellazioni.
- I contenuti letti entrano nella conversazione e quindi nella memoria dell'agente
  (STM/LTM) come qualsiasi altro tool: valutare quali share esporre di conseguenza.

## Risoluzione dei problemi

| Sintomo / codice | Causa probabile | Azione |
|------------------|-----------------|--------|
| `credentials_missing` | L'utente non ha configurato il connettore | Le mie integrazioni → inserire utente e password |
| `auth_failed` ripetuto senza nuovi tentativi | Blocco locale attivo dopo un logon errato | L'utente aggiorna le credenziali (il blocco cade da solo) |
| `account_locked` | Account bloccato da AD | Sblocco da parte dell'IT; il blocco locale scade dopo la finestra configurata |
| `password_expired` | Password scaduta o da cambiare | Cambiarla in Windows, poi aggiornarla in chat-ui |
| `access_denied` | ACL NTFS o permessi di share | Verificare i diritti dell'utente sul file server |
| `share_not_allowed` | Share fuori allowlist | L'admin la aggiunge in Impostazioni → File server |
| `unreachable` / `timeout` | Rete, DNS o firewall (TCP 445) | **Testa connessione** dal backend; controllare `dns:` e firewall |
| `not_configured` | Connettore disabilitato o senza host/share | Completare e salvare la configurazione admin |

## Fuori scope (roadmap)

Autenticazione Kerberos, cancellazione file, più file server per tenant, enumerazione
automatica delle share, badge «credenziali non valide» in chat-ui, namespace DFS.

## Test

```bash
python -m pytest src/test/ -k "smb" -v
```

I test usano `smbclient` mockato; non serve un server SMB.
