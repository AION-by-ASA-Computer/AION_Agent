---
title: Speech-to-text MCP (stt)
sidebar_position: 13
description: Trascrizione di file audio della sessione con servizio Whisper OpenAI-compatibile o faster-whisper locale, a chunk con budget e resume.
---

# Speech-to-text MCP (`stt`)

Il server `stt` (`mcp_servers/stt_mcp/server.py`) è il gemello audio del server `ocr`: dato un file audio caricato in chat (mp3, wav, ogg/opus, m4a, flac, webm o un video con traccia audio) ne estrae il testo con il tool **`transcribe_audio`**.

La logica (decodifica, chunking, budget/resume, scrittura del transcript) vive in [`src/tools/audio_transcribe.py`](../../src/tools/audio_transcribe.py), così altri chiamanti (es. i vocali WhatsApp in una fase successiva) possono riusarla senza passare da MCP.

## Due modalità, come l'OCR

| Modalità | Quando | Motore |
|----------|--------|--------|
| **remote** | `AION_STT_BASE_URL` impostato **e** `AION_STT_API_KEY` impostato e diverso da `EMPTY` | `POST {AION_STT_BASE_URL}/audio/transcriptions` (API OpenAI-compatibile: vLLM con Whisper, speaches, OpenAI) |
| **local** | in tutti gli altri casi | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) su CPU (CTranslate2, `int8`) |

Il manifest restituito riporta sempre `engine` (`local` / `remote`) e `model`.

:::note Non esiste uno speech-to-text "senza AI"
Le alternative più leggere (PocketSphinx, Vosk) sono comunque modelli statistici, con qualità molto inferiore in italiano. faster-whisper `small` in `int8` gira su CPU senza GPU, con punteggiatura, VAD e rilevamento della lingua.
:::

### Esempio servizio remoto (vLLM)

```bash
vllm serve openai/whisper-large-v3 --port 8000
```

```bash
AION_STT_BASE_URL=http://gpu-host:8000/v1
AION_STT_API_KEY=token-qualsiasi   # diverso da EMPTY
AION_STT_MODEL=openai/whisper-large-v3
```

## Il tool `transcribe_audio`

```python
transcribe_audio(relative_path: str, language: str = "", start_sec: float = 0,
                 max_duration_sec: float = 0, budget_sec: float = 90.0,
                 force: bool = False) -> str  # JSON manifest
```

| Parametro | Significato |
|-----------|-------------|
| `relative_path` | File nella sessione (`uploads/…`, `derived/…`, `workspace/…`) |
| `language` | Codice ISO (`it`, `en`, …). Vuoto = `AION_STT_LANGUAGE`; `auto` = rilevamento automatico |
| `start_sec` / `max_duration_sec` | Finestra da trascrivere (`0` = fino alla fine) |
| `budget_sec` | Tempo massimo della chiamata; limitato a `AION_MCP_TOOL_RESULT_TIMEOUT - 25` |
| `force` | Ritrascrive tutto ignorando i chunk già presenti |

### Output nella sessione

```
derived/audio/<slug>/
├── chunks/c0000.txt, c0001.txt, …   # una riga "[mm:ss] testo" per segmento
├── transcript.txt                    # concatenazione dei chunk
└── manifest.json                     # ultimo manifest (senza il testo)
```

Il manifest contiene `ok`, `engine`, `model`, `language`, `language_detected`, `duration_sec`, `transcribed_until_sec`, `partial`, `resume_from_sec`, `failed_chunks`, `transcript_path`, `chars`, `grep_hint`. Il testo completo è incluso in `text` se non supera `AION_STT_INLINE_MAX_CHARS`; oltre, il manifest porta solo un `excerpt` e l'agente cerca nel transcript con `sandbox_grep_content`.

### Chunking, budget e resume

Lo schema è lo stesso di `doc_ingest`:

1. L'audio viene decodificato **un chunk alla volta** (PyAV, ricampionato a 16 kHz mono), quindi la memoria resta limitata anche su registrazioni di ore.
2. Ogni chunk finito viene scritto subito in `chunks/cNNNN.txt`; una chiamata successiva **salta** i chunk già presenti.
3. Prima di ogni chunk si stima se il chunk più lento visto finora sta ancora nel budget. Se no, il tool restituisce `partial: true` e `resume_from_sec`: l'agente richiama `transcribe_audio` con `start_sec=resume_from_sec`.
4. Cambiare la dimensione del chunk (es. passando da locale a remoto) invalida i chunk esistenti, che vengono riscritti.
5. Se il primo chunk fallisce, il tool si ferma con `error: "engine_failed"` e un `hint` sul motore; i fallimenti successivi finiscono in `failed_chunks` senza interrompere il resto.

Se la chiamata supera comunque il timeout del bridge MCP, il messaggio di timeout suggerisce di richiamare il tool con un `budget_sec` più basso: i chunk già scritti non vanno persi.

### Errori

| `error` | Causa |
|---------|-------|
| `path_error` | Path fuori dalla sessione o inesistente |
| `not_audio` | Nessuna traccia audio (per PDF/immagini usare `ocr_file` / `doc_ingest`) |
| `too_large` / `too_long` | Oltre `AION_STT_MAX_AUDIO_BYTES` / `AION_STT_MAX_DURATION_SEC` |
| `decoder_unavailable` | PyAV non installato |
| `engine_failed` | Modello locale non caricabile o errore HTTP del servizio remoto |
| `empty_range` | `start_sec` oltre la fine del file |

## Variabili d'ambiente

| Variabile | Default | Uso |
|-----------|---------|-----|
| `AION_STT_BASE_URL` | vuoto | Endpoint OpenAI-compatibile (senza `/audio/transcriptions`) |
| `AION_STT_API_KEY` | `EMPTY` | Vuoto o `EMPTY` → modalità locale |
| `AION_STT_MODEL` | `openai/whisper-large-v3` | Modello remoto |
| `AION_STT_TIMEOUT` | `120` | Timeout HTTP per chunk (secondi) |
| `AION_STT_LANGUAGE` | `it` | Lingua di default (`auto` = rilevamento) |
| `AION_STT_CHUNK_SEC` | `30` | Chunk remoto (Whisper su vLLM accetta al massimo 30 s) |
| `AION_STT_LOCAL_MODEL` | `small` | Nome faster-whisper (`tiny`, `base`, `small`, `medium`, `large-v3-turbo`, `large-v3`) o path di una directory CTranslate2. Modificabile da admin-ui |
| `AION_STT_LOCAL_MODEL_DIR` | vuoto (Docker: `/opt/aion/models/faster-whisper`) | Cartella extra di modelli già presenti, controllata per prima. I download vanno sempre in `<AION_DATA_DIR>/models/faster-whisper` |
| `AION_STT_LOCAL_COMPUTE_TYPE` | `int8` | Quantizzazione CTranslate2 |
| `AION_STT_LOCAL_CPU_THREADS` | `0` (auto) | Thread CPU |
| `AION_STT_LOCAL_BEAM_SIZE` | `5` | Beam search (1 = greedy, più veloce). Modificabile da admin-ui |
| `AION_STT_LOCAL_CHUNK_SEC` | `60` | Chunk locale (faster-whisper fa già il windowing interno a 30 s) |
| `AION_STT_MAX_AUDIO_BYTES` | `104857600` (100 MB) | Dimensione massima del file |
| `AION_STT_MAX_DURATION_SEC` | `7200` (2 h) | Durata massima |
| `AION_STT_INLINE_MAX_CHARS` | `8000` | Testo restituito inline nel manifest |

## Modello locale: download, RAM e prestazioni

- **Risoluzione del modello**: se `AION_STT_LOCAL_MODEL` è una directory viene usata così com'è; altrimenti si cerca `<nome>/model.bin` prima in `AION_STT_LOCAL_MODEL_DIR` (se impostato) e poi in `<AION_DATA_DIR>/models/faster-whisper`. Se manca, il modello viene scaricato da Hugging Face in quest'ultima cartella al primo uso (`small` ≈ 460 MB su disco), oppure in anticipo da admin-ui.
- **Docker**: [`docker/Dockerfile.backend`](../../docker/Dockerfile.backend) pre-scarica il modello al build (`ARG STT_LOCAL_MODEL=small`) in `/opt/aion/models/faster-whisper`, quindi a runtime non serve rete. Per un altro modello: `docker compose build --build-arg STT_LOCAL_MODEL=large-v3-turbo backend` e lo stesso valore in `AION_STT_LOCAL_MODEL`. Un modello diverso scelto da admin-ui viene invece scaricato nel volume `aion_data` e sopravvive alla ricreazione del container.
- **Nessun ffmpeg di sistema**: la decodifica usa PyAV, che faster-whisper installa con le librerie FFmpeg incluse.
- **RAM per sessione**: `stt` è un server *session-scoped* (`AION_MCP_SESSION_SCOPED_SERVERS`), quindi **ogni chat che lo usa avvia un proprio worker e carica il modello** (picco misurato con `small` int8: ~850 MB). Il server è "cold": parte solo alla prima chiamata a `transcribe_audio` (riscaldato da `tool_search`), non al boot. Su host con molte chat concorrenti conviene la modalità remota o un modello più piccolo (`base`).
- **Velocità indicativa** (`small` int8, Apple Silicon, modello già caricato): ~3× più veloce del tempo reale. Su CPU server x86 aspettarsi valori simili o inferiori; per registrazioni lunghe l'agente procede a più chiamate con resume.

## Configurazione da admin-ui

**Impostazioni → Audio** ([`admin-ui/components/settings/SttSection.tsx`](../../admin-ui/components/settings/SttSection.tsx)) sceglie il motore come la sezione OCR, spiegando le opzioni a parole senza mostrare i nomi delle variabili:

- **Modello remoto**: URL del servizio (`AION_STT_BASE_URL`, senza `/audio/transcriptions`: se incollato viene tolto), chiave API (`AION_STT_API_KEY`, mascherata) e **Testa connessione**, che interroga `GET /models` tramite `POST /admin/llm-providers/probe` e propone i modelli di trascrizione trovati (`whisper`, `voxtral`, `parakeet`, …) per `AION_STT_MODEL`; se il servizio non li elenca il nome si inserisce a mano. Dopo il test compaiono i limiti `AION_STT_TIMEOUT` e `AION_STT_CHUNK_SEC` (max 30 s con Whisper su vLLM). Come per il backend, serve una chiave reale (non `EMPTY`).
- **Su questo server**: le scelte della tabella sotto. Salvando in questa modalità le variabili remote (`AION_STT_BASE_URL`, `AION_STT_MODEL`, `AION_STT_API_KEY`, `AION_STT_TIMEOUT`, `AION_STT_CHUNK_SEC`) vengono svuotate, così il backend torna a faster-whisper.

| Scelta in UI (modalità locale) | Variabile | Opzioni |
|--------------|-----------|---------|
| Modello di riconoscimento vocale | `AION_STT_LOCAL_MODEL` | `tiny`, `base`, `small` (consigliato), `medium`, `large-v3-turbo`, `large-v3`, con dimensione, memoria e uso tipico; un valore impostato a mano resta visibile come "personalizzato" |
| Lingua predefinita | `AION_STT_LANGUAGE` | Italiano (default), inglese, francese, tedesco, spagnolo, rilevamento automatico (`auto`); un altro codice ISO resta visibile come "personalizzato". Il tool può comunque ricevere un `language` diverso per singolo file |
| Precisione della trascrizione | `AION_STT_LOCAL_BEAM_SIZE` | Veloce (1), Bilanciato (3), Accurato (5, consigliato); un altro valore resta visibile come "personalizzato" |

La lingua è modificabile solo in modalità locale ma non viene svuotata passando al remoto: `resolve_language` continua a inviarla anche al servizio esterno.

- Il salvataggio passa dal normale `/admin/settings` e vale per le conversazioni avviate dopo (i worker `stt` già attivi mantengono il vecchio modello).
- Per ogni modello la sezione mostra se è già sul server. Se quello scelto manca, il pulsante **Scarica ora** lo scarica in background ([`src/api/admin_stt.py`](../../src/api/admin_stt.py)):
  - `GET /admin/stt/local-models`: modalità (`local`/`remote`), modello corrente, modelli con `installed`/`custom`, stato del download;
  - `POST /admin/stt/local-models/{name}/download`: accetta solo i nomi della lista (400 `unknown_model` altrimenti), un download alla volta (409 `download_in_progress`).
- In Docker il salvataggio riavvia il container: conviene attendere la fine del download prima di salvare (i file già scaricati restano e un nuovo tentativo riprende da lì).
- Se è configurato un servizio remoto, la sezione lo segnala: le scelte locali entrano in uso solo senza servizio remoto.

## Registrazione

- [`config_std/mcp_registry.yaml`](../../config_std/mcp_registry.yaml): voce `stt` (`python -u stt_mcp/server.py`).
- Profili `aion_std`, `generic_assistant`, `document_extractor`: `stt` in `mcp_servers`.
- [`src/runtime/tool_exposure.py`](../../src/runtime/tool_exposure.py): `transcribe_audio` → `stt` in `_KNOWN_COLD_TOOLS`.

## Uso fuori da MCP: vocali WhatsApp

Il canale WhatsApp trascrive i vocali **prima** del turno chiamando
`transcribe_audio_file` direttamente nel processo backend
([`src/channels/whatsapp/voice.py`](../../src/channels/whatsapp/voice.py)), con
lo stesso motore e le stesse variabili `AION_STT_*` del server MCP. L'output va
nella stessa cartella `derived/audio/<slug>/` della conversazione, quindi una
successiva chiamata a `transcribe_audio` sullo stesso file riusa i chunk già
scritti, e la pipeline (`load_audio_manifest`) segnala all'agente che l'audio è
già trascritto. Dettagli in
[Canale WhatsApp → Messaggi vocali](../integrations/whatsapp.md#messaggi-vocali).
