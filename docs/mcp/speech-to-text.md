---
title: Speech-to-text (stt)
sidebar_position: 13
description: Transcribes audio files from a chat session, using an OpenAI-compatible Whisper service or local faster-whisper, in chunks with a time budget and resume. Also powers voice dictation in chat-ui.
---

# Speech-to-text (`stt`)

The `stt` server turns speech into text. When a user uploads an audio file to the chat (mp3, wav,
ogg/opus, m4a, flac, webm, or a video with an audio track), the agent can transcribe it with the
**`transcribe_audio`** tool; the same engines also power the microphone (voice dictation) button
in chat-ui. Transcription runs either on a remote Whisper service or locally on the server's CPU,
with no extra setup needed. This page is for **administrators** choosing the engine and for
**developers/operators** who want the details.

:::note Terms used on this page
- **MCP** (Model Context Protocol): the standard AION uses to plug tools and connectors into the agent. `stt` is an MCP server (`mcp_servers/stt_mcp/server.py`), the audio twin of the `ocr` server.
- **Whisper**: OpenAI's open speech-recognition model. **faster-whisper** is an optimised local implementation of it.
:::

The logic (decoding, chunking, budget/resume, writing the transcript) lives in
[`src/tools/audio_transcribe.py`](../../src/tools/audio_transcribe.py), so other callers (for
example WhatsApp voice messages, see [below](#use-outside-mcp-whatsapp-voice-messages)) can reuse
it without going through MCP.

## Two modes, like OCR

| Mode | When | Engine |
|------|------|--------|
| **remote** | `AION_STT_BASE_URL` is set **and** `AION_STT_API_KEY` is set and not `EMPTY` | `POST {AION_STT_BASE_URL}/audio/transcriptions` (OpenAI-compatible API: vLLM with Whisper, speaches, OpenAI) |
| **local** | in every other case | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on CPU (CTranslate2, `int8`) |

The returned manifest always reports `engine` (`local` / `remote`) and `model`.

:::note There is no speech-to-text "without AI"
The lighter alternatives (PocketSphinx, Vosk) are still statistical models, with much lower
quality in Italian. faster-whisper `small` in `int8` runs on CPU without a GPU, with punctuation,
VAD (voice activity detection) and language detection.
:::

### Example remote service (vLLM)

```bash
vllm serve openai/whisper-large-v3 --port 8000
```

```bash
AION_STT_BASE_URL=http://gpu-host:8000/v1
AION_STT_API_KEY=any-token   # anything other than EMPTY
AION_STT_MODEL=openai/whisper-large-v3
```

## Configuration from admin-ui {#configurazione-da-admin-ui}

**Settings → Audio** ([`admin-ui/components/settings/SttSection.tsx`](../../admin-ui/components/settings/SttSection.tsx))
chooses the engine, like the OCR section, explaining the options in words without showing variable
names:

- **Remote model**: service URL (`AION_STT_BASE_URL`, without `/audio/transcriptions`: if pasted,
  it is removed), API key (`AION_STT_API_KEY`, masked) and **Test connection**, which queries
  `GET /models` via `POST /admin/llm-providers/probe` and suggests the transcription models it finds
  (`whisper`, `voxtral`, `parakeet`, …) for `AION_STT_MODEL`; if the service does not list them, type
  the name by hand. After the test, the `AION_STT_TIMEOUT` and `AION_STT_CHUNK_SEC` limits appear
  (max 30 s with Whisper on vLLM). As for the backend, a real key is required (not `EMPTY`).
- **On this server**: the choices in the table below. Saving in this mode clears the remote
  variables (`AION_STT_BASE_URL`, `AION_STT_MODEL`, `AION_STT_API_KEY`, `AION_STT_TIMEOUT`,
  `AION_STT_CHUNK_SEC`), so the backend goes back to faster-whisper.

| UI choice (local mode) | Variable | Options |
|------------------------|----------|---------|
| Speech recognition model | `AION_STT_LOCAL_MODEL` | `tiny`, `base`, `small` (recommended), `medium`, `large-v3-turbo`, `large-v3`, each with size, memory and typical use; a value set by hand is shown as "custom" |
| Default language | `AION_STT_LANGUAGE` | Italian (default), English, French, German, Spanish, automatic detection (`auto`); any other ISO code is shown as "custom". The tool can still receive a different `language` per file |
| Transcription accuracy | `AION_STT_LOCAL_BEAM_SIZE` | Fast (1), Balanced (3), Accurate (5, recommended); any other value is shown as "custom" |

The language can only be edited in local mode, but it is not cleared when switching to remote:
`resolve_language` keeps sending it to the external service too.

- Saving goes through the normal `/admin/settings` and applies to conversations started afterwards
  (`stt` workers already running keep the old model).
- For each model, the section shows whether it is already on the server. If the chosen one is
  missing, the **Download now** button downloads it in the background
  ([`src/api/admin_stt.py`](../../src/api/admin_stt.py)):
  - `GET /admin/stt/local-models`: mode (`local`/`remote`), current model, models with
    `installed`/`custom`, download status;
  - `POST /admin/stt/local-models/{name}/download`: accepts only names from the list
    (400 `unknown_model` otherwise), one download at a time (409 `download_in_progress`).
- In Docker, saving restarts the container: wait for the download to finish before saving (files
  already downloaded are kept, and a new attempt resumes from there).
- If a remote service is configured, the section says so: the local choices are only used when
  there is no remote service.

## Voice dictation from chat-ui {#dettatura-da-chat-ui}

The microphone button in the chat-ui composer uses the same engines (remote or local
faster-whisper) but **does not go through the MCP tool**: the backend calls
`transcribe_audio_to_text` from [`src/tools/audio_transcribe.py`](../../src/tools/audio_transcribe.py)
in-process ([`src/api/v1/voice.py`](../../src/api/v1/voice.py)). This way the local model is loaded
only once for the whole backend, and the text comes back in a few seconds, without an agent turn.

How it works for the user:

- The text is inserted in the text box at the cursor: the user reads it over and sends it. Esc
  cancels the recording.
- With the local model, dictations are serialised (one at a time).
- The browser only grants the microphone in a secure context: HTTPS or `localhost`. With the Docker
  stack over HTTP (`DOMAIN=:80`), the button only works when the chat is opened on `localhost`.
- **Privacy:** the recording is written to a temporary folder that is deleted right afterwards; it
  does not go to `uploads/` (so it is not attached to the message) and the text is not logged.

API:

- `GET /v1/voice/status` → `{enabled, mode, max_duration_sec, max_bytes}`. `enabled` is true if
  `AION_CHAT_VOICE_INPUT` is not `0` **and** an engine is ready: a remote service is configured, or
  faster-whisper is installed with the local model already on disk (otherwise the button stays
  hidden: download the model from admin-ui → Settings → Audio).
- `POST /v1/voice/transcribe` (multipart `file`, optional `language` = the chat-ui language) →
  `{text, language, duration_sec}`. Errors: 413 `too_large`, 422 `too_long` / `not_audio` / `empty`,
  503 `voice_input_disabled` / `engine_failed` / `decoder_unavailable`.

| Variable | Default | Description |
|----------|---------|-------------|
| `AION_CHAT_VOICE_INPUT` | `1` | `0` hides the microphone button |
| `AION_STT_DICTATION_MAX_SEC` | `300` | Maximum length of one dictation (chat-ui stops one second earlier) |
| `AION_STT_DICTATION_MAX_BYTES` | `10485760` | Maximum size of one recording |

## The `transcribe_audio` tool

```python
transcribe_audio(relative_path: str, language: str = "", start_sec: float = 0,
                 max_duration_sec: float = 0, budget_sec: float = 90.0,
                 force: bool = False) -> str  # JSON manifest
```

| Parameter | Meaning |
|-----------|---------|
| `relative_path` | File in the session (`uploads/…`, `derived/…`, `workspace/…`) |
| `language` | ISO code (`it`, `en`, …). Empty = `AION_STT_LANGUAGE`; `auto` = automatic detection |
| `start_sec` / `max_duration_sec` | Time window to transcribe (`0` = until the end) |
| `budget_sec` | Maximum time for the call; capped at `AION_MCP_TOOL_RESULT_TIMEOUT - 25` |
| `force` | Re-transcribes everything, ignoring chunks already present |

### Output in the session

```
derived/audio/<slug>/
├── chunks/c0000.txt, c0001.txt, …   # one "[mm:ss] text" line per segment
├── transcript.txt                    # concatenation of the chunks
└── manifest.json                     # latest manifest (without the text)
```

The manifest contains `ok`, `engine`, `model`, `language`, `language_detected`, `duration_sec`,
`transcribed_until_sec`, `partial`, `resume_from_sec`, `failed_chunks`, `transcript_path`, `chars`,
`grep_hint`. The full text is included in `text` if it does not exceed `AION_STT_INLINE_MAX_CHARS`;
beyond that, the manifest only carries an `excerpt` and the agent searches the transcript with
`sandbox_grep_content`.

### Chunking, budget and resume

The scheme is the same as `doc_ingest`:

1. The audio is decoded **one chunk at a time** (PyAV, resampled to 16 kHz mono), so memory stays
   bounded even on recordings that last hours.
2. Each finished chunk is written immediately to `chunks/cNNNN.txt`; a later call **skips** chunks
   already present.
3. Before each chunk, the tool estimates whether the slowest chunk seen so far still fits in the
   budget. If not, it returns `partial: true` and `resume_from_sec`: the agent calls
   `transcribe_audio` again with `start_sec=resume_from_sec`.
4. Changing the chunk size (e.g. switching from local to remote) invalidates existing chunks, which
   are rewritten.
5. If the first chunk fails, the tool stops with `error: "engine_failed"` and a `hint` about the
   engine; later failures go into `failed_chunks` without interrupting the rest.

If the call still exceeds the MCP bridge timeout, the timeout message suggests calling the tool
again with a lower `budget_sec`: chunks already written are not lost.

### Errors

| `error` | Cause |
|---------|-------|
| `path_error` | Path outside the session or does not exist |
| `not_audio` | No audio track (for PDFs/images use `ocr_file` / `doc_ingest`) |
| `too_large` / `too_long` | Over `AION_STT_MAX_AUDIO_BYTES` / `AION_STT_MAX_DURATION_SEC` |
| `decoder_unavailable` | PyAV not installed |
| `engine_failed` | Local model cannot be loaded, or HTTP error from the remote service |
| `empty_range` | `start_sec` is past the end of the file |

## Environment variables

| Variable | Default | Use |
|----------|---------|-----|
| `AION_STT_BASE_URL` | empty | OpenAI-compatible endpoint (without `/audio/transcriptions`) |
| `AION_STT_API_KEY` | `EMPTY` | Empty or `EMPTY` → local mode |
| `AION_STT_MODEL` | `openai/whisper-large-v3` | Remote model |
| `AION_STT_TIMEOUT` | `120` | HTTP timeout per chunk (seconds) |
| `AION_STT_LANGUAGE` | `it` | Default language (`auto` = detection) |
| `AION_STT_CHUNK_SEC` | `30` | Remote chunk size (Whisper on vLLM accepts at most 30 s) |
| `AION_STT_LOCAL_MODEL` | `small` | faster-whisper name (`tiny`, `base`, `small`, `medium`, `large-v3-turbo`, `large-v3`) or path to a CTranslate2 directory. Editable from admin-ui |
| `AION_STT_LOCAL_MODEL_DIR` | empty (Docker: `/opt/aion/models/faster-whisper`) | Extra folder of pre-installed models, checked first. Downloads always go to `<AION_DATA_DIR>/models/faster-whisper` |
| `AION_STT_LOCAL_COMPUTE_TYPE` | `int8` | CTranslate2 quantisation |
| `AION_STT_LOCAL_CPU_THREADS` | `0` (auto) | CPU threads |
| `AION_STT_LOCAL_BEAM_SIZE` | `5` | Beam search (1 = greedy, faster). Editable from admin-ui |
| `AION_STT_LOCAL_CHUNK_SEC` | `60` | Local chunk size (faster-whisper already does internal 30 s windowing) |
| `AION_STT_MAX_AUDIO_BYTES` | `104857600` (100 MB) | Maximum file size |
| `AION_STT_MAX_DURATION_SEC` | `7200` (2 h) | Maximum duration |
| `AION_STT_INLINE_MAX_CHARS` | `8000` | Text returned inline in the manifest |

## Local model: download, RAM and performance

- **Model resolution**: if `AION_STT_LOCAL_MODEL` is a directory, it is used as-is; otherwise
  `<name>/model.bin` is looked up first in `AION_STT_LOCAL_MODEL_DIR` (if set) and then in
  `<AION_DATA_DIR>/models/faster-whisper`. If missing, the model is downloaded from Hugging Face into
  that last folder on first use (`small` ≈ 460 MB on disk), or ahead of time from admin-ui.
- **Docker**: [`docker/Dockerfile.backend`](../../docker/Dockerfile.backend) pre-downloads the model
  at build time (`ARG STT_LOCAL_MODEL=small`) into `/opt/aion/models/faster-whisper`, so no network
  is needed at runtime. For another model: `docker compose build --build-arg STT_LOCAL_MODEL=large-v3-turbo backend`
  and the same value in `AION_STT_LOCAL_MODEL`. A different model chosen from admin-ui is instead
  downloaded into the `aion_data` volume and survives container re-creation.
- **No system ffmpeg**: decoding uses PyAV, which faster-whisper installs with bundled FFmpeg
  libraries.
- **RAM per session**: `stt` is a *session-scoped* server (`AION_MCP_SESSION_SCOPED_SERVERS`), so
  **every chat that uses it starts its own worker and loads the model** (measured peak with `small`
  int8: ~850 MB). The server is "cold": it starts only at the first `transcribe_audio` call (warmed
  up by `tool_search`), not at boot. On hosts with many concurrent chats, the remote mode or a
  smaller model (`base`) is a better fit.
- **Indicative speed** (`small` int8, Apple Silicon, model already loaded): ~3× faster than real
  time. On x86 server CPUs expect similar or lower values; for long recordings the agent proceeds
  in several calls with resume.

## Registration

- [`config_std/mcp_registry.yaml`](../../config_std/mcp_registry.yaml): `stt` entry
  (`python -u stt_mcp/server.py`).
- Profiles `aion_std`, `generic_assistant`, `document_extractor`: `stt` in `mcp_servers`.
- [`src/runtime/tool_exposure.py`](../../src/runtime/tool_exposure.py): `transcribe_audio` → `stt`
  in `_KNOWN_COLD_TOOLS`.

## Use outside MCP: WhatsApp voice messages

The WhatsApp channel transcribes voice messages **before** the turn by calling
`transcribe_audio_file` directly in the backend process
([`src/channels/whatsapp/voice.py`](../../src/channels/whatsapp/voice.py)), with the same engine and
the same `AION_STT_*` variables as the MCP server. The output goes into the same
`derived/audio/<slug>/` folder of the conversation, so a later `transcribe_audio` call on the same
file reuses the chunks already written, and the pipeline (`load_audio_manifest`) tells the agent
the audio is already transcribed. Details in
[WhatsApp channel → Voice messages](../integrations/whatsapp.md#messaggi-vocali).
