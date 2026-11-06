---
title: Telegram - Runbook
sidebar_position: 2
description: Avvio, configurazione e checklist di test manuale del canale Telegram di AION.
---

# AION × Telegram — Runbook

Il canale gira **dentro il processo AION**: lo avvia e lo ferma il `_lifespan` di
`src/api/main.py`. Per default riceve gli update con long polling, quindi serve solo traffico in
uscita verso `api.telegram.org:443`, senza webhook né tunnel. In alternativa può ricevere gli update
via **webhook** (vedi "Modalità webhook").

## Configurazione (Admin → Telegram → Configurazione)

La configurazione del canale si gestisce **solo** dall'**Admin UI → Telegram → Configurazione**
(`GET/PUT /admin/telegram/settings`) e vive **solo nel database**: tabella `tg_settings`, una riga per tenant,
con tutti i valori (token del manager compreso) in un unico JSON cifrato con
`AION_CREDENTIAL_ENCRYPTION_KEY`. Il `.env` non viene letto, né come valore iniziale né come fallback: i campi
mai salvati usano i default qui sotto, e se nell'ambiente restano variabili `AION_TELEGRAM_*` il log segnala
che sono ignorate.

La pagina mostra anche lo stato del bot manager (connesso, Bot Management Mode, assistenti in ascolto, chiave
di cifratura) e un pulsante **Verifica token** (`getMe` su Telegram, senza salvare). Il token non viene mai
restituito: il campo mostra solo le ultime 4 cifre di quello salvato e lasciarlo vuoto non lo cambia.
Al salvataggio la nuova configurazione si applica **subito, senza riavviare l'API né il container**: il gateway
Telegram si ferma e riparte da solo con i nuovi valori (log: `telegram: impostazioni riapplicate`). Ogni
salvataggio lascia nel registro operazioni una riga `settings_updated` con i soli nomi dei campi cambiati.

Nella tabella, la prima colonna è il nome del campo (quello usato dall'API e nel resto di questo documento).

| Campo | Default | Note |
|---|---|---|
| `enabled` | `0` | con `0` AION non carica nulla del canale |
| `manager_token` | — | token del bot manager da @BotFather; mai in git |
| `proxy_url` | — | `http://`, `https://` o `socks5://` (proxy aziendale) |
| `delivery_mode` | `polling` | come arrivano gli update: `polling` (long polling, default) o `webhook` (Telegram chiama AION su un URL pubblico HTTPS, vedi "Modalità webhook") |
| `polling_timeout` | `50` | secondi di long polling per `getUpdates` (solo in modalità `polling`) |
| `shutdown_grace_sec` | `10` | attesa degli handler in corso allo shutdown (fisso, non modificabile dall'Admin UI) |
| `pairing_code_ttl_min` | `15` | validità (minuti) dei link di collegamento |
| `manager_chat` | `0` | `0`: il bot manager gestisce solo account e assistenti, si chatta con gli assistenti personali. `1`: riattiva la chat sul manager (`/new`, `/profile`, `/project`, `/stop`), da usare solo in emergenza o per demo |
| `default_profile` | `generic_assistant` | profilo proposto per primo (⭐) nel wizard `/newbot`; con `manager_chat=1` è anche il profilo iniziale della chat sul manager |
| `max_concurrent_jobs` | `1` | turni dell'agente in parallelo; gli altri attendono in coda |
| `stream_edit_interval_ms` | `1000` | frequenza di aggiornamento della risposta in streaming |
| `turn_timeout_sec` | `900` | durata massima di un turno avviato da Telegram |
| `default_thinking_level` | — | ragionamento dei turni Telegram: `off`, `min`, `medium`, `max`; vuoto = default di sistema (`AION_DEFAULT_REASONING_EFFORT`). Come su WhatsApp, viene copiato nei metadati della conversazione e il composer della Chat UI lo mostra |
| `max_outbound_files` | `5` | file generati dall'agente in un turno rimandati in chat; gli altri restano nella sessione e il bot scrive "📁 Altri N file sono disponibili su AION" |
| `rich_messages` | `1` | risposte nel formato rich di Telegram (vedi "Fase 7"); `0` = solo HTML |
| `show_reasoning` | `1` | ragionamento del modello in una sezione richiudibile (solo formato rich) |
| `show_tools` | `1` | mostra i tool chiamati (in streaming e in un riquadro in fondo alla risposta) |
| `max_running_bots` | `200` | bot personali in ascolto contemporaneamente (rete di sicurezza; oltre il limite un bot non viene avviato e il log lo segnala) |
| `reconcile_interval_min` | `30` | controllo periodico degli assistenti (vedi "Ciclo di vita"); `0` lo disattiva |
| `max_bots_per_user` | `3` | bot personali per utente AION creati con `/newbot` (gli eliminati non contano) |
| `allowed_profiles` | — | policy del canale (allowlist stretta): profili (slug separati da virgola) usabili da Telegram; vuoto = nessuno |
| `allowed_projects` | — | policy del canale (allowlist stretta): progetti (slug separati da virgola) usabili da Telegram; vuoto = nessuno (resta sempre possibile "Nessun progetto") |
| `AION_CREDENTIAL_ENCRYPTION_KEY` | — | chiave già usata da AION per le credenziali: cifra anche i token dei bot personali. Senza, in sviluppo si usa una chiave insicura; in produzione `/newbot` è disattivato. In Admin → Impostazioni compare mascherata (`***`) |

Dipendenze: `aiogram[proxy]` in `requirements.txt` (`uv pip install -r requirements.txt`).

## Avvio

```bash
uvicorn src.api.main:app --reload --reload-exclude data/sessions
```

Log attesi con il flag acceso (logger `aion.telegram`):

- `telegram: gateway avviato (long polling)` (oppure `(webhook)`)
- `telegram: bot manager @<username> (id=…) can_manage_bots=True|False`

Se `can_manage_bots=False`, aprire la **Mini App di @BotFather** (pulsante *Open* nella chat,
oppure `https://t.me/BotFather?startapp`), scegliere il bot e attivare **Bot Management Mode**
(sezione *Mode Settings*). Nel menu testuale `/mybots` l'opzione non c'è. Serve dalla Fase 4.

## Comportamenti garantiti

- **L'avvio di AION non dipende da Telegram.** La connessione avviene in background; errori di rete
  o proxy vengono ritentati con backoff (fino a 60 s).
- **Token rifiutato (401).** Il gateway si ferma con un errore nei log, mentre AION continua a funzionare.
- **Nessun update perso allo stop.** L'offset confermato a Telegram non supera mai un update ancora
  in lavorazione; allo shutdown si attendono gli handler (grace) e si conferma solo ciò che è completato.
  Al riavvio, gli update non confermati vengono riconsegnati (al massimo un duplicato, mai una perdita).
- **I messaggi inviati mentre AION è spento** restano in coda su Telegram (fino a 24 h) e vengono
  elaborati al riavvio.
- **I token non compaiono nei log**, nemmeno dentro gli URL della Bot API nelle eccezioni.
- **Conflitto 409** (due istanze in polling sullo stesso token): viene loggato e ritentato.
  Non avviare due AION con lo stesso token.

## Modalità webhook

Con **Ricezione degli update = Webhook** (`delivery_mode=webhook`, Admin → Telegram → Connessione) ogni bot
del canale, cioè il manager e ogni assistente personale attivo, registra su Telegram (`setWebhook`) l'URL

```
<URL pubblico dell'API>/v1/channels/telegram/webhook/<bot id>
```

e Telegram vi invia gli update con una `POST`. L'URL pubblico è lo stesso usato per il callback di
WhatsApp (`AION_OAUTH_REDIRECT_BASE_URL` / `AION_PUBLIC_API_URL`); dietro Caddy è
`https://<dominio>/api/v1/channels/telegram/webhook/<bot id>`. Telegram accetta solo **HTTPS** sulle porte
443, 80, 88 o 8443 e un host raggiungibile da Internet (niente `localhost`).

- **Autenticazione**: ogni webhook ha un `secret_token` derivato dal token del bot (HMAC, nulla da salvare);
  Telegram lo rimanda nell'header `X-Telegram-Bot-Api-Secret-Token` e l'endpoint
  (`src/api/v1/telegram_webhook.py`) rifiuta con 401 le richieste senza.
- **Risposta immediata**: l'endpoint risponde 200 appena accetta l'update e il turno gira in background,
  così Telegram non ritenta durante i turni lunghi. Gli update duplicati (`update_id` già visto) vengono
  ignorati. Con il bot non ancora in ascolto (gateway in riavvio) risponde 503 e Telegram ritenta.
- **Registrazione automatica**: il webhook si registra a ogni avvio del gateway (anche dopo un salvataggio
  in Admin), quindi segue da solo un URL che cambia, come quello del tunnel di test. Un assistente sospeso,
  eliminato o con un token nuovo perde il proprio webhook; allo shutdown di AION i webhook restano e Telegram
  tiene in coda gli update fino al riavvio. Tornando a `polling`, i poller rimuovono il webhook all'avvio.
- **Compromesso**: a differenza del polling, un update ancora in lavorazione quando AION si ferma non viene
  riconsegnato (l'update era già stato confermato con il 200). Per la produzione il polling resta la scelta
  più robusta.
- **Diagnostica**: il riquadro Stato di Admin → Telegram mostra la modalità, l'URL che AION registra, un
  eventuale problema (URL pubblico mancante o non HTTPS, `setWebhook` rifiutato) e quanto riporta Telegram
  (`getWebhookInfo`: URL registrato, update in coda, ultimo errore di consegna).

### Test in locale con il tunnel

`scripts/whatsapp-tunnel.sh` apre un quick tunnel Cloudflare (`https://<random>.trycloudflare.com`) verso
Caddy e riavvia lo stack con gli URL pubblici puntati al tunnel: vale anche per Telegram.

1. `scripts/whatsapp-tunnel.sh` (con `DOMAIN=:80` nel `.env`);
2. Admin → Telegram → Connessione → **Ricezione degli update = Webhook** → Salva;
3. nel riquadro Stato l'URL del webhook deve essere quello del tunnel e "Update in attesa" scendere a 0
   dopo un messaggio al bot.

L'URL del tunnel cambia a ogni avvio dello script: il backend viene ricreato e registra da solo il nuovo
webhook, senza passaggi manuali. Chiuso il tunnel, tornare a `polling` (o rilanciare lo script), altrimenti
Telegram accumula gli update su un URL non più raggiungibile.

## Amministrazione (Fase 8)

**Admin UI → Telegram** (`/telegram`, gruppo *Operazioni*):

- **Assistenti.** Tutti i bot dell'installazione (mai i token): nome, username, stato, modalità, in ascolto o
  no, proprietario (utente AION e account Telegram), profilo, progetto, ultimo uso. Azioni:
  **Sospendi / Riattiva** (il proprietario riceve un avviso sul manager), **Elimina** (revoca del token;
  conferma digitando lo username) e **Riassegna**. Senza gateway attivo l'eliminazione disattiva il bot in
  AION ma non può revocare il token: la pagina lo segnala.
- **Riassegna** serve quando un bot viene trasferito a un altro account Telegram da @BotFather: AION lo
  sospende e ne registra il nuovo account; se quell'account ha collegato AION, l'admin conferma e il bot
  passa al suo utente AION, torna attivo e il nuovo proprietario riceve un avviso.
- **Quote.** Per ogni utente con Telegram collegato (o con assistenti) si può fissare un numero massimo di
  assistenti diverso da `max_bots_per_user`; vuoto = valore predefinito. `0` impedisce di crearne.
- **Registro.** Le ultime operazioni del canale (`tg_audit`): collegamenti, creazioni, cambi di
  configurazione e modalità, sospensioni, eliminazioni, rotazioni di token, riassegnazioni, quote.
- **Policy del canale** (Admin → Telegram → Configurazione → Assistenti personali):
  `allowed_profiles` / `allowed_projects`, scelti da due elenchi a spunta. È un'allowlist stretta: solo i
  profili e progetti selezionati compaiono in `/newbot`, `/mybots`, `/profile`, `/project`; con l'elenco
  vuoto non è consentito nulla e i profili/progetti creati in seguito vanno abilitati esplicitamente. Se un
  assistente usa già un profilo o progetto non consentito, ogni messaggio viene rifiutato con "non
  disponibile su Telegram (policy dell'amministratore)". Il pannello avvisa se nessun profilo è
  consentito o se il profilo suggerito (`default_profile`) non è tra quelli consentiti.
- **Le chat Telegram sono sessioni AION normali.** Compaiono nella sidebar della Chat UI (con l'icona di
  Telegram) e si possono continuare da lì, come quelle WhatsApp; vedi "Chat con l'agente".

### Rotazione della chiave di cifratura

La configurazione del canale e i token dei bot sono cifrati con `AION_CREDENTIAL_ENCRYPTION_KEY` (la stessa
delle credenziali MCP per utente). Cambiare la chiave rende **illeggibili** i valori salvati: il canale riparte
spento finché la configurazione non viene salvata di nuovo da Admin → Telegram (token del manager compreso), e
i bot passano in errore ("token non decifrabile"). Procedura consigliata:

1. Nuova chiave: `openssl rand -hex 32`, impostata nel `.env` (non nell'Admin UI, dove è mascherata).
2. Riavvia AION, poi reinserisci la configurazione da Admin → Telegram e salva.
3. I bot in errore si recuperano da soli al controllo periodico se il manager riesce a ottenere di nuovo il
   token (`getManagedBotToken`, che lo salva cifrato con la nuova chiave); altrimenti il proprietario usa
   `/mybots` → **🔑 Rigenera token** o **Riprova configurazione**.
4. Le credenziali MCP per utente cifrate con la vecchia chiave vanno reinserite dagli utenti.

### Troubleshooting

| Sintomo | Causa probabile | Cosa fare |
|---|---|---|
| Nessuna riga `telegram:` nei log | canale non attivo in Admin → Telegram | Attivarlo e salvare: il gateway parte senza riavvio |
| `configurazione salvata non decifrabile` nei log | `AION_CREDENTIAL_ENCRYPTION_KEY` cambiata o assente | Ripristinare la chiave, oppure riconfigurare e salvare da Admin → Telegram |
| `token rifiutato da Telegram (401)` per il manager | token del manager errato o revocato | Admin → Telegram → Configurazione → **Verifica token**, incollare quello nuovo |
| `can_manage_bots=False` | Bot Management Mode spenta | Mini App di @BotFather → bot → Mode Settings → Bot Management Mode |
| `/newbot` dice che manca la chiave di cifratura | `AION_CREDENTIAL_ENCRYPTION_KEY` assente in produzione | Impostarla nel `.env` e riavviare |
| `conflitto 409` nei log | due istanze di AION sullo stesso token | Lasciarne una sola |
| Il bot nel gruppo non risponde alle menzioni | privacy mode di Telegram | Usare `/ask@nome_bot` o rendere il bot amministratore del gruppo |
| L'assistente esce da un gruppo appena aggiunto | assistente personale, oppure aggiunto da chi non è il creatore | Renderlo condiviso (`/mybots`) e farlo aggiungere al creatore |
| "non disponibile su Telegram (policy…)" | profilo/progetto nella policy del canale | Admin → Telegram → Configurazione → profili/progetti esclusi |
| Assistente "sospeso: proprietario cambiato" | bot trasferito su @BotFather a un altro account | Admin → Telegram → **Riassegna** (il nuovo account deve aver collegato AION) |
| `messaggi rich non disponibili` | il bot non supporta i messaggi rich | Nessuna azione: si usa l'HTML; `rich_messages=0` per forzarlo |
| La build del sito docs fallisce su questo file | `<parola>` fuori da un blocco di codice (MDX) | Metterla tra backtick |

## Checklist di test manuale — Fase 8

1. Admin UI → **Telegram**: compaiono tutti gli assistenti con proprietario, modalità, stato e ultimo uso.
2. **Sospendi** un assistente: smette di rispondere e il proprietario riceve l'avviso; **Riattiva**: torna.
3. **Elimina** (digitando lo username): sparisce dall'elenco (visibile con "Mostra eliminati").
4. Quote: imposta `0` a un utente e prova `/newbot` con quell'account: viene rifiutato; svuota la quota e riprova.
5. Registro: compaiono le operazioni appena fatte.
6. Admin → Telegram → Configurazione: metti un profilo in "Profili esclusi" e salva: sparisce da `/newbot`, e un
   assistente che lo usa risponde "non disponibile su Telegram".
7. Apri una chat Telegram nella Chat UI e scrivi un messaggio: l'agente risponde nella stessa conversazione.
8. Admin → Impostazioni: `AION_CREDENTIAL_ENCRYPTION_KEY` non è più leggibile.

## Collegamento account (Fase 2)

Ogni utente collega il proprio account Telegram dalla **Chat UI → Impostazioni → Telegram**:

1. **Collega Telegram** genera un link monouso `https://t.me/<bot>?start=pair_<codice>` (più un QR),
   valido `pairing_code_ttl_min` minuti. Generarne uno nuovo invalida il precedente.
2. L'utente apre il link dal telefono e preme **Avvia**: il bot riscatta il codice e collega
   l'account Telegram all'utente AION. La pagina delle impostazioni si aggiorna da sola.
3. Un utente AION ha al massimo un account Telegram, e un account Telegram al massimo un utente AION.
   Collegando un nuovo account Telegram, quello precedente viene sostituito.

Regole:

- **Sicurezza del link.** Il link è una credenziale temporanea: chi lo apre entro la scadenza collega il
  *proprio* Telegram al tuo utente. Non va condiviso. Nel DB c'è solo lo SHA-256 del codice.
- **Accesso al bot.** Chi non è collegato può usare solo `/start`, `/help` e `/whoami`; ogni altro
  messaggio riceve l'invito a collegarsi. Il bot manager risponde solo in chat privata.
- **Scollegamento.** Con `/unlink` dal bot o **Scollega** dalla Chat UI (in questo caso il bot avvisa
  l'utente su Telegram). L'effetto è immediato: il collegamento viene riletto a ogni messaggio.
- **Utente eliminato.** Se l'admin elimina un utente AION, collegamento e codici spariscono (FK `ON DELETE CASCADE`).
- **Audit.** Ogni azione (codice creato, collegato, scollegato) è registrata in `tg_audit`.
- **Tabelle.** `tg_links`, `tg_pairing_codes` e `tg_audit` vengono create dalla migrazione `t0g1l2k029`
  sulle installazioni esistenti, oppure all'avvio del canale sui DB nuovi.

## Ruoli: bot manager e assistenti personali

- **Bot manager** (`manager_token`, uno per installazione): collegamento dell'account
  (`/start`, `/me`, `/unlink`, `/whoami`) e gestione degli assistenti (`/newbot`, `/mybots`, `/cancel`).
  **Non chatta con l'agente**: al testo libero risponde con i pulsanti per aprire gli assistenti
  dell'utente, oppure ricorda che può crearne uno con `/newbot`. La creazione non è mai obbligatoria
  né proposta in automatico: parte solo dall'utente.
- **Assistenti personali** (Fase 4/5): l'unico posto dove si chatta con l'agente, ognuno con il suo
  profilo e progetto, accessibili solo al proprietario.
- **Chat UI → Impostazioni → Telegram**: stato del collegamento ed elenco degli assistenti con link
  "Apri". Le chat Telegram sono nella sidebar, come le altre conversazioni.
- Con `manager_chat=1` il manager torna a chattare come descritto qui sotto.

## Chat con l'agente (Fase 3)

Un utente collegato scrive al bot e risponde l'agente AION, **a nome del suo utente AION**: stessa
memoria, stessi permessi su profili e progetti, stessa pipeline della Chat UI. Vale per gli assistenti
personali e, solo con `manager_chat=1`, per il bot manager (`/profile` e `/project` sono
comandi del manager).

- **Conversazioni = sessioni AION.** Ogni chat Telegram punta a una conversazione AION (`tg_sessions`:
  bot, chat, thread, utente → conversazione), che ricorda il contesto finché non si usa `/new`, come
  `/nuova` su WhatsApp. È una sessione vera, indistinguibile da una della Chat UI: marcata
  `metadata.source = "telegram"`, titolata dal primo messaggio, con upload, file generati e memoria della
  sessione. Il turno usa la stessa logica di WhatsApp, in `src/channels/session_turn.py`:
  - **Chat UI.** La conversazione compare subito nella sidebar con l'icona di Telegram e si continua da lì:
    stessa cronologia, si scrive, si rigenera, si valuta. La risposta finale su Telegram ha in fondo il link
    "💬 Continua su AION" (solo se `AION_PUBLIC_CHAT_URL` non è `localhost`).
  - **Turno seguibile dal vivo.** Mentre l'agente risponde su Telegram, il turno è registrato come run in
    background (`_background_runs` + redis `stream_active`): aprendo la conversazione nella Chat UI lo
    streaming si vede in diretta (`/v1/chat/stream/reconnect`). Lo stop dalla Chat UI ferma anche la
    risposta su Telegram.
  - **Ragionamento.** Livello `default_thinking_level` del canale, copiato in `metadata.thinking_enabled` /
    `metadata.reasoning_effort` a ogni turno.
  - **Allegati.** All'agente arrivano i file del messaggio ("nuovi") e tutti gli upload precedenti della
    sessione ("storici"), come nella Chat UI.
  - **File generati.** Quelli creati dall'agente nel turno (CSV, PDF, grafici...) tornano in chat: jpeg/png
    fino a 10 MB come foto, il resto come documento (limite dei bot: 50 MB). Al massimo
    `max_outbound_files` per turno; gli altri restano nella sessione.
- **Profilo e progetto.** Profilo iniziale `default_profile`; `/profile` e `/project`
  mostrano solo ciò che l'utente può usare. Valgono dal messaggio successivo, nella stessa conversazione.
- **Streaming.** In chat privata si usa `sendMessageDraft` (anteprima animata, poi messaggio finale).
  Se Telegram lo rifiuta, il bot passa da solo all'invio di un messaggio aggiornato ogni
  `stream_edit_interval_ms`; nei log compare `sendMessageDraft non disponibile`.
- **Tool.** Durante la risposta compare l'elenco dei tool chiamati (⏳ in corso, ✓ riuscito, ✗ errore),
  anche per quelli che durano pochi millisecondi; nel messaggio finale resta un riquadro richiudibile
  "🔧 Strumenti usati". Si disattiva con `show_tools=0`.
- **Tool "a richiesta".** Con `AION_DEFER_TOOL_GROUPS=1` (default AION) alcuni gruppi, tra cui
  `web_research`, vengono caricati solo se il modello chiama `activate_tool_group`. Se non lo fa, risponde
  di non avere la ricerca web: è lo stesso comportamento della Chat UI, non del canale.
- **Formattazione.** Il Markdown dell'agente diventa HTML Telegram: grassetto, corsivo, codice, link,
  citazioni, elenchi; le tabelle restano allineate in un blocco monospazio. Le risposte oltre i 4096
  caratteri sono divise in più messaggi, senza spezzare i blocchi di codice.
- **Coda.** Al massimo `max_concurrent_jobs` turni insieme per tutti gli utenti; due messaggi
  rapidi nella stessa chat vengono eseguiti uno dopo l'altro. Chi aspetta riceve "⏳ In coda (posizione N)".
- **Stop e limiti.** `/stop` interrompe la risposta (la parte già scritta resta, con "⏹️ Risposta interrotta").
  Dopo `turn_timeout_sec` il turno viene fermato.
- **Riavvio di AION.** I turni in corso vengono interrotti e l'utente riceve "AION si sta riavviando".
  Un crash del processo durante un turno perde quella risposta: va riformulata la domanda.
- **Per ora solo testo.** Foto, documenti e vocali ricevono un messaggio di cortesia (Fase 7).

## Bot personali (Fase 4)

Ogni utente collegato può creare dal bot manager i propri bot ("managed bot" di Telegram), senza
aprire @BotFather e senza toccare il `.env`. Richiede **Bot Management Mode** attiva sul manager
(all'avvio il log riporta `can_manage_bots=True`).

- **`/newbot`.** Procedura guidata: nome → profilo (solo quelli consentiti all'utente) → progetto
  (se ce ne sono) → riepilogo. Alla conferma compare il pulsante **🤖 Crea il bot**: Telegram chiede
  di confermare nome e username (deve finire con `bot`). In alternativa c'è un link
  `t.me/newbot/<manager>/<username>`. La richiesta vale 30 minuti; `/cancel` la annulla.
  Durante la procedura il testo scritto è il nome del bot, non una domanda all'agente; un altro
  comando la interrompe.
- **Registrazione.** Telegram avvisa il manager (`managed_bot_created` e `managed_bot`); AION recupera
  il token con `getManagedBotToken`, lo salva **cifrato** in `tg_bots` (mai in chiaro nel DB o nei log),
  imposta comandi e descrizioni del bot e limita l'accesso al solo proprietario
  (`setManagedBotAccessSettings`). L'utente riceve "✅ @nome_bot è pronto".
- **Quota.** Al massimo `max_bots_per_user` bot per utente. Un bot creato fuori dalla
  procedura (link diretto) oltre la quota viene registrato ma resta sospeso.
- **`/mybots`.** Elenco con stato (in configurazione, attivo, sospeso, errore) e, per ogni bot:
  cambio profilo e progetto, sospendi/riattiva, "Riprova configurazione" se è in errore, elimina.
- **Eliminazione.** Marca il bot come eliminato, ne ferma l'ascolto e revoca il token
  (`replaceManagedBotToken`, il nuovo token viene scartato). La revoca fa arrivare da Telegram un update
  "token cambiato", che per un bot eliminato viene ignorato (log: `update per il bot eliminato ... ignorato`).
  La Bot API non permette di cancellare il bot: resta visibile su Telegram, ma non risponde più;
  per rimuoverlo del tutto si usa @BotFather.
- **Eventi successivi.** Se il token viene rigenerato da @BotFather, AION salva quello nuovo. Se il bot
  passa a un altro account Telegram, viene sospeso e il vecchio proprietario avvisato.

## Chat sui bot personali (Fase 5)

- **Ascolto.** All'avvio AION mette in ascolto (long polling) tutti i bot personali **attivi**; i bot
  creati, riattivati o con token rigenerato entrano o rientrano in ascolto subito, senza riavvio. Sospesi,
  eliminati e in errore non vengono ascoltati. Nel log: `N bot personali in ascolto`, `bot @x in ascolto`.
- **Costo.** Ascoltare un bot significa tenere aperta una richiesta `getUpdates` in attesa: niente CPU e
  nessuna chiamata al modello. Il lavoro parte solo all'arrivo di un messaggio e passa dalla **stessa coda**
  del bot manager (`max_concurrent_jobs` vale per tutti i bot insieme). Conversazione e
  sessione nascono al primo messaggio; i server MCP inattivi vengono spenti dal core dopo
  `AION_MCP_POOL_IDLE_SEC` e ricreati al messaggio successivo.
- **Configurazione.** Risponde l'agente con profilo e progetto del bot, riletti a ogni messaggio: un
  cambio da `/mybots` vale dal messaggio successivo. Le conversazioni appartengono all'utente AION
  proprietario, con `metadata.telegram_bot = <username>`, e compaiono nella sidebar della Chat UI.
- **Comandi del bot.** `/start`, `/help`, `/new`, `/stop`, `/status` (profilo e progetto),
  `/project` (cambia il progetto del bot, come da `/mybots`).
- **Accesso.** Solo il proprietario, con l'account Telegram collegato allo stesso utente AION che ha
  creato il bot. Telegram stesso limita già l'accesso al proprietario (`setManagedBotAccessSettings`).
- **Errori.** Se Telegram rifiuta il token (401) il bot passa in stato errore, esce dall'ascolto e il
  proprietario riceve un avviso sul bot manager.
- **Una sola istanza.** Ogni token ha un solo consumer per processo. Due istanze di AION sullo stesso DB
  ricevono 409 da Telegram (`conflitto 409` nel log) e si alternano male: usarne una sola.

## Assistenti personali e condivisi

In `/newbot`, dopo il nome, si sceglie la **modalità** (cambiabile poi da `/mybots` → assistente):

| | 🔒 Personale | 👥 Condiviso |
|---|---|---|
| Chi può scrivere | solo il creatore | qualunque utente AION che abbia collegato Telegram |
| Identità AION del turno | del creatore | **di chi scrive** (suoi permessi, memoria, conversazioni) |
| Accesso Telegram (`setManagedBotAccessSettings`) | ristretto al proprietario | aperto: il controllo lo fa AION |
| Gruppi | no (esce da solo) | **disattivati per ora**; con il flag attivo, solo il creatore può aggiungerlo |
| Profilo e progetto | quelli del bot | quelli del bot (vedi "Progetto nei gruppi") |

- **Gruppi disattivati (2026-11).** Per ora gli assistenti non funzionano nei gruppi:
  `GROUPS_ENABLED = False` in `src/channels/telegram/groups.py`. Un assistente aggiunto a un gruppo, o che
  riceve un messaggio da un gruppo, scrive "Gli assistenti AION nei gruppi non sono ancora disponibili" ed
  esce; il menu dei gruppi (`/ask`) non viene registrato e i testi di `/newbot` e `/mybots` non citano i
  gruppi. "Condiviso" vale quindi solo in chat privata. Il codice dei gruppi resta e i suoi test girano con
  il flag attivo. Prima di riattivarli bisogna togliere il contesto del gruppo dal messaggio utente salvato
  (vedi "Contesto del gruppo"): con le chat Telegram diventate sessioni della Chat UI, quel prefisso
  comparirebbe nella cronologia. Va passato al turno come contesto di sistema. Le voci qui sotto descrivono
  il comportamento con il flag attivo.
- **Progetto nei gruppi (decisione 2026-10-30).** In chat privata con un assistente condiviso vale il
  controllo per persona: chi non è membro del progetto del bot riceve un rifiuto. **Nei gruppi** invece il
  progetto si usa con i **permessi del creatore**: chiunque nel gruppo può fare domande e leggere le risposte,
  anche con dati del progetto, perché le risposte nel gruppo le vedono comunque tutti. È responsabilità di chi
  aggiunge il bot (solo il creatore) metterlo in gruppi le cui persone possono vedere quei dati, ad esempio
  un gruppo dedicato. Conversazione e memoria personale restano di chi scrive; se il creatore perde l'accesso
  al progetto, nel gruppo arriva il rifiuto. Implementazione: delega per conversazione e per turno
  (`src/runtime/project_access_delegation.py`), letta dal controllo d'accesso della pipeline, dal contesto e
  dai tool della memoria SQL e dagli hook pre/post turno; senza deleghe il core si comporta come prima.
- Chi scrive a un assistente condiviso senza aver collegato Telegram riceve l'invito a farlo.
- Solo il creatore può cambiare progetto (`/project`) e impostazioni (`/mybots`).
- **Gruppi.** L'assistente risponde solo ai messaggi rivolti a lui: menzione `@nome_bot`, risposta a un suo
  messaggio, oppure `/ask domanda`. La risposta cita la domanda ed è visibile a tutti; niente anteprima
  animata (`sendMessageDraft` funziona solo in privato). Ogni partecipante ha la propria conversazione AION
  (`/new` la ricomincia), marcata con `metadata.telegram_chat = <titolo del gruppo>`.
- **Contesto del gruppo.** Domande e risposte rivolte all'assistente nel gruppo sono salvate in
  `tg_group_messages` (ultime 50 per gruppo). A ogni nuova domanda l'agente riceve, prima del testo, le
  domande degli **altri** partecipanti fatte dopo l'ultima domanda di chi scrive (al massimo 8, troncate),
  più il titolo del gruppo e il nome di chi chiede. Questo prefisso finisce anche nel messaggio salvato
  nella conversazione di chi chiede.
- **Ingresso nei gruppi.** Se un assistente condiviso viene aggiunto da qualcuno che non è il creatore, o se
  l'assistente è personale, scrive un messaggio ed esce dal gruppo.
- **Privacy mode (verificato).** Con la privacy mode di Telegram attiva (default) nei gruppi il bot riceve
  solo i comandi indirizzati a lui (`/ask@nome_bot domanda`, che il menu `/` inserisce da solo) e le
  risposte ai suoi messaggi: **le menzioni `@nome_bot domanda` non arrivano**. La Bot API non permette di
  cambiarla. Per abilitare le menzioni: **rendere il bot amministratore del gruppo** (gli amministratori
  ricevono tutti i messaggi; l'assistente risponde comunque solo a quelli rivolti a lui), oppure disattivare
  la privacy mode da @BotFather (Bot Settings → Group Privacy) e riaggiungere il bot al gruppo.
  Il messaggio di benvenuto spiega come fare domande in base al caso; alla promozione ad amministratore
  l'assistente avvisa che ora risponde anche alle menzioni.

## Risposte, stop, allegati (Fase 7)

- **Formato rich** (`sendRichMessage`, Bot API 10.x): il Markdown dell'agente viene inviato così com'è
  (Markdown in stile GitHub): **tabelle vere**, codice con linguaggio, titoli, elenchi. Come nella Chat UI,
  con `show_reasoning=1` la risposta si apre con "💭 Ragionamento" (richiudibile); in fondo
  "🔧 Strumenti usati". Mentre il modello ragiona l'anteprima mostra "💭 Sto ragionando…".
  Anteprima in privato con `sendRichMessageDraft`, nei gruppi con un messaggio rich modificato.
- **Ripiego HTML automatico.** Se Telegram rifiuta il formato rich per un bot (log: `messaggi rich non
  disponibili`), quel bot passa all'HTML di prima fino al riavvio. Un testo che Telegram non riesce a
  leggere, o una risposta oltre ~30.000 caratteri, usa l'HTML (diviso in più messaggi) solo per quella risposta.
- **Pulsante di stop.** In chat privata l'anteprima animata mostra il pulsante nativo di stop
  (`can_stop`): premendolo arriva l'update `stopped_message_generation` e AION interrompe il turno, come
  `/stop` (la parte già scritta resta, con "⏹️ Risposta interrotta"). Nei gruppi resta `/stop`.
- **Allegati.** Documenti e foto inviati all'assistente vengono scaricati, salvati in `uploads/` della
  conversazione come gli upload della Chat UI (conversione Word e indicizzazione automatica) e allegati alla
  domanda. Con la didascalia la domanda parte subito. **Senza didascalia** (Telegram su Android invia i
  documenti senza farla scrivere) il bot conferma "📎 Ricevuto …, ora scrivi cosa vuoi che faccia" e allega
  i file al **messaggio successivo** della stessa persona (entro 15 minuti; `/new` li scarta; un riavvio di
  AION li dimentica). Più file inviati di seguito si accumulano; gli album di foto si raccolgono insieme con
  la loro didascalia. Limite 20 MB per file (limite di Telegram per i bot; oltre, il bot avvisa). Nei gruppi solo se l'allegato è rivolto al bot (risposta a
  un suo messaggio o didascalia con `/ask@nome_bot`).
- **Vocali.** La Bot API non offre trascrizione (quella di Telegram Premium avviene solo nell'app di chi la
  usa): il bot risponde di scrivere la domanda.
- **Conferme dei tool pericolosi** (punto 7.5 del piano): non implementate. Richiedono un meccanismo di
  approvazione nel core di AION (oggi `src/security/approval_manager.py` è uno stub non usato).

## Checklist di test manuale — Fase 7

1. Chiedi a un assistente "fammi una tabella con 3 città e i loro abitanti": arriva una tabella vera; in
   fondo le sezioni richiudibili (strumenti, ragionamento se il modello ragiona).
2. Fai una domanda lunga e premi il pulsante di stop sull'anteprima: la risposta si ferma con
   "⏹️ Risposta interrotta".
3. Invia un PDF con didascalia "riassumilo": l'agente lo legge; nella Chat UI (sidebar) la chat mostra
   l'allegato. Una domanda successiva sul PDF, senza reinviarlo, funziona (upload storici).
4b. Chiedi un file ("esportami i dati in CSV"): arriva come documento su Telegram ed è nella sessione della
   Chat UI. Con più di `max_outbound_files` file arriva "📁 Altri N file sono disponibili su AION".
4. Invia una foto senza didascalia: l'agente la descrive.
5. Invia un file oltre 20 MB: il bot avvisa del limite.
6. Invia un vocale: il bot chiede di scrivere la domanda.
7. Nel gruppo: rispondi a un messaggio dell'assistente con una foto e una didascalia: risponde citando.
8. Con `rich_messages=0` le risposte tornano in HTML.

## Ciclo di vita degli assistenti (Fase 6)

- **Account Telegram scollegato** (`/unlink` o Chat UI → Impostazioni → Telegram): gli assistenti attivi
  vengono sospesi (motivo "account Telegram scollegato") e smettono di ascoltare; il messaggio di
  scollegamento li elenca. Al **ricollegamento con lo stesso account** tornano attivi da soli. Con un account
  Telegram diverso restano sospesi: per Telegram il proprietario è ancora quello che li ha creati.
  Gli assistenti sospesi a mano o per la quota non vengono toccati.
- **Utente AION eliminato** (Admin → Utenti): prima della cancellazione AION ferma l'ascolto dei suoi
  assistenti, ne **revoca i token** e rimuove collegamento, sessioni, codici e richieste in sospeso.
  Con il gateway spento i bot vengono comunque disattivati in AION, ma i token non si possono revocare
  (log: `eliminato senza revoca del token`).
- **🔑 Rigenera token** (`/mybots` → assistente): nuovo token con `replaceManagedBotToken`, salvato cifrato,
  ascolto riavviato una sola volta; quello vecchio smette di funzionare.
- **Controllo periodico** ogni `reconcile_interval_min` minuti, per ogni assistente non eliminato:
  - aggiorna nome e username se cambiati su Telegram;
  - un assistente in errore che risponde di nuovo torna attivo (il proprietario riceve un avviso);
  - token rifiutato: se il manager ottiene un nuovo token (cambio non notificato) lo salva e riavvia;
    se Telegram non conosce più il bot (cancellato da @BotFather) lo segna eliminato e avvisa il proprietario;
  - errori di rete: non cambia nulla, riprova al giro successivo.

## Checklist di test manuale — Assistenti condivisi

1. `/newbot` → nome → **👥 Condiviso** → profilo → crea. Il messaggio "pronto" indica la modalità.
2. Un collega con Telegram collegato al **suo** utente AION scrive all'assistente in privato: risponde con
   i permessi del collega; nella Chat UI del collega la chat compare nella sidebar.
3. Un account Telegram non collegato scrive all'assistente: riceve l'invito a collegarsi.
4. Il collega prova `/project`: "Solo il creatore…".
5. **Con i gruppi disattivati (default)**: aggiungi l'assistente a un gruppo, scrive "Gli assistenti AION
   nei gruppi non sono ancora disponibili" ed esce. I punti 5b-8 valgono solo con `GROUPS_ENABLED = True`.
5b. Il creatore aggiunge l'assistente a un gruppo: messaggio di benvenuto. Un altro membro che prova ad
   aggiungerlo a un suo gruppo: l'assistente scrive "Solo il creatore…" ed esce.
6. Nel gruppo: "ciao a tutti" → nessuna risposta; `/ask@nome_bot domanda` o risposta a un suo messaggio
   → risposta che cita la domanda. Rendi il bot amministratore: arriva "Ora rispondo anche quando mi
   menzionate" e funziona anche `@nome_bot domanda`.
7. Un secondo membro chiede "e invece …?" rispondendo all'assistente: la risposta tiene conto della domanda
   precedente dell'altro membro.
8. `/mybots` → assistente → **🔒 Rendi personale**: nel gruppo, alla menzione successiva, l'assistente esce.

## Checklist di test manuale — Fase 6

1. `/unlink` sul manager: il messaggio elenca gli assistenti sospesi; scrivendo a un assistente non risponde.
2. Ricollega dalla Chat UI (stesso account Telegram): il messaggio di collegamento dice "Assistenti di
   nuovo attivi" e l'assistente risponde di nuovo.
3. Ripeti lo scollegamento dalla Chat UI: su Telegram arriva l'avviso con gli assistenti sospesi.
4. `/mybots` → assistente → **🔑 Rigenera token**: l'assistente continua a rispondere; nel log c'è un solo
   `bot @... in ascolto` dopo la rotazione.
5. Rinomina l'assistente da @BotFather; con `reconcile_interval_min=1` entro un minuto
   `/mybots` mostra il nuovo nome.
6. Cancella un assistente da @BotFather: al controllo successivo arriva "non esiste più su Telegram" e
   sparisce da `/mybots`.
7. Crea un utente di prova con un assistente, poi eliminalo da Admin → Utenti: l'assistente smette di
   rispondere e nel log compare `utente ... eliminato, 1 assistenti revocati`.

## Checklist di test manuale — Manager senza chat

1. Ricostruisci backend e chat-ui (`manager_chat` assente o `0`).
2. Sul manager il menu comandi non ha più `/new`, `/profile`, `/project`, `/stop`; `/help` mostra
   "Assistenti personali" e "Account".
3. Scrivi "ciao" al manager: nessuna risposta dell'agente, ma i pulsanti "💬 nome assistente" che aprono
   i tuoi assistenti (o il suggerimento `/newbot` se non ne hai).
4. `/mybots`: accanto a ogni assistente attivo c'è "💬 Apri".
5. `/newbot` → il profilo di default compare per primo con ⭐.
6. Chat UI → Impostazioni → Telegram: riquadro "I tuoi assistenti" con stato, profilo, progetto e "Apri";
   nelle chat Telegram compare l'assistente (`@...`) o "bot di gestione".

## Checklist di test manuale — Fase 5

1. Ricostruisci il backend; nel log: `1 bot personali in ascolto` e `bot @aonasabot in ascolto`.
2. Apri `@aonasabot`: `/start` risponde con nome, profilo e progetto.
3. Scrivi una domanda: risponde l'agente con il profilo del bot (tool visibili come sul manager).
4. `/status` mostra la configurazione; `/project` cambia il progetto e `/mybots` sul manager lo riflette.
5. Dal manager `/mybots` → cambia profilo → la domanda successiva sul bot usa il nuovo profilo.
6. `/mybots` → Sospendi → sul bot non arriva più risposta; Riattiva → risponde di nuovo, senza riavvio.
7. Domanda sul manager e sul bot personale quasi insieme: la seconda mostra "⏳ In coda".
8. Chat UI: le chat del bot personale compaiono nella sidebar con l'icona di Telegram e si continuano da lì.
9. Riavvia il backend: il bot personale torna in ascolto da solo.

## Checklist di test manuale — Fase 4

1. Ricostruisci il backend; nel log: `bot manager @... can_manage_bots=True`.
2. Sul manager `/help`: compaiono `/newbot`, `/mybots`, `/cancel`.
3. `/newbot` → scrivi un nome → scegli un profilo → (progetto) → **✅ Crea il bot**.
4. Premi **🤖 Crea il bot** sotto il campo di scrittura e conferma in Telegram.
5. Entro pochi secondi arriva "✅ @..._bot è pronto" con profilo e progetto; la tastiera sparisce.
6. Apri il nuovo bot: il menu ha `/new`, `/project`, `/stop`, `/status`, `/help` e la descrizione AION.
7. `/mybots` → il bot è 🟢 attivo; prova Profilo, Progetto, Sospendi/Riattiva.
8. `/newbot` → scrivi "ciao" come nome → `/cancel`: nessuna risposta dell'agente durante la procedura.
9. Elimina il bot da `/mybots`: sparisce dall'elenco; eventualmente cancellalo da @BotFather.
10. DB: `SELECT id, username, status, length(token_enc) FROM tg_bots;` — il token non è leggibile.

## Checklist di test manuale — Fase 3

Prerequisito: `docker compose up -d --build backend chat-ui`; account Telegram già collegato (Fase 2).

1. [ ] Nei log del backend: `gateway avviato`, nessun errore di migrazione (`t1s2e3s030`).
2. [ ] Toccando `/` nel bot il menu mostra new, profile, project, stop, start, help, me, unlink, whoami.
3. [ ] Scrivi una domanda lunga (es. "spiegami in 10 punti come funziona un database relazionale"):
       compare "Sto pensando…"/"sta scrivendo…", il testo cresce progressivamente, poi resta il messaggio finale formattato.
4. [ ] Fai una domanda di seguito ("e il secondo punto in dettaglio?"): la risposta tiene conto della precedente.
5. [ ] Chat UI: la conversazione è nella sidebar con l'icona di Telegram e il titolo della prima domanda.
       Aprila durante una risposta lunga: lo streaming si vede in diretta. Scrivi un messaggio dalla Chat UI:
       risponde nella stessa conversazione, e la domanda successiva da Telegram ne tiene conto.
6. [ ] Una domanda che richiede uno strumento (es. ricerca web): compare la riga "🔧 …" durante l'uso.
7. [ ] `/stop` durante una risposta lunga: "⏹️ Interrompo…" e la risposta si chiude con "Risposta interrotta".
8. [ ] Due messaggi rapidi uno dopo l'altro: il secondo riceve "⏳ In coda" e viene risposto dopo il primo.
9. [ ] `/profile` → pulsanti con i profili consentiti (✓ su quello attuale) → sceglierne un altro → la
       risposta successiva usa quel profilo. `/project` → idem, incluso "Nessun progetto".
10. [ ] `/new` → "Nuova conversazione"; la domanda successiva non ricorda il contesto; nella sidebar
        della Chat UI ci sono ora due chat.
11. [ ] Invia una foto o un vocale: risposta "Per ora posso rispondere solo a messaggi di testo".
12. [ ] Riavvia il backend durante una risposta: arriva "AION si sta riavviando: risposta interrotta".

## Checklist di test manuale — Fase 2

Prerequisito: ricostruire backend e Chat UI (`docker compose up -d --build backend chat-ui`).

1. [ ] Nei log del backend: `gateway avviato` e `can_manage_bots=True`, nessun errore di migrazione.
2. [ ] Dal telefono, **prima di collegarti**: `ciao` → "Questo account Telegram non è collegato ad AION…";
       `/whoami` funziona; `/me` → stesso messaggio "non collegato".
3. [ ] Chat UI → Impostazioni: c'è la voce **Telegram** con stato "Non collegato".
4. [ ] **Collega Telegram** → compaiono QR, "Apri in Telegram" e l'orario di scadenza.
5. [ ] Inquadra il QR (o apri il link) dal telefono → **Avvia** → il bot risponde "✅ Account collegato
       all'utente AION …"; entro pochi secondi la pagina mostra "Collegato" con @username e date.
6. [ ] Dal telefono: `/me` mostra il tuo utente AION; `ciao` → "Il tuo account è collegato…".
7. [ ] Riapri lo stesso link → "Questo link è già stato usato".
8. [ ] Chat UI → **Scollega** → conferma → il bot ti scrive "scollegato da AION dalla Chat UI";
       `ciao` torna a ricevere "non collegato".
9. [ ] Ricollega, poi `/unlink` dal telefono → la pagina, ricaricata, torna "Non collegato".
10. [ ] Genera un link e lascialo scadere: la pagina mostra "Il link è scaduto…"; aprirlo dal telefono →
        "Link di collegamento scaduto".
11. [ ] (Se hai un secondo account Telegram) collega il tuo utente con l'account A, poi apri un nuovo link
        con l'account B: B diventa quello collegato e A torna "non collegato".

## Checklist di test manuale — Fase 1

Prerequisiti: punti 1–5 e 7 del § 1 del piano (bot manager creato, token salvato in Admin → Telegram).

1. [ ] Con il canale non attivo AION parte come prima: nei log nessuna riga `aion.telegram`.
2. [ ] Attivato e salvato da Admin → Telegram (senza riavviare AION) compaiono `gateway avviato` e la riga `can_manage_bots=…`.
3. [ ] Dal telefono: `/start` riceve il saluto in meno di 2 s.
4. [ ] `/whoami` restituisce il proprio user id: annotarlo (prerequisito 6 del piano).
5. [ ] `/help` mostra l'elenco; il menu comandi del client (tasto `/`) contiene start, help, whoami.
6. [ ] Un testo libero in chat privata riceve il messaggio "Per ora rispondo solo ai comandi…".
7. [ ] Fermare AION (Ctrl+C): nei log `offset confermato allo shutdown` (se c'erano update) e `gateway fermato`.
8. [ ] Con AION spento inviare `/whoami` e un testo; riavviare AION: entrambi ricevono risposta.
9. [ ] Riavviare di nuovo AION senza scrivere nulla: nessuna risposta duplicata.
10. [ ] Token errato salvato in Admin → Telegram: AION parte comunque e logga `rifiutato da Telegram (401)`.
