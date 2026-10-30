---
name: audio_transcription_protocol
description: "Protocol for audio and video files in the session (meetings, voice notes, interviews, calls): transcribe_audio with resume on long recordings, language choice, reading and searching the transcript, citing [mm:ss] timestamps."
tags: [protocol, audio, stt, transcription, voice, meeting]
status: verified
source: curated
version: 1
---

# Audio Transcription Protocol

## When this applies

The user uploads or points to an audio file (mp3, wav, m4a, ogg/opus voice note, flac,
aac, webm) or a video with an audio track, or asks to transcribe, summarize, take
minutes of, or find something said in a recording.

The only way to read audio is the `transcribe_audio` tool (MCP server `stt`). It is
loaded on demand: if it is not in your tool list, find it with `tool_search` first.

## Never do these

| Shortcut | Why it fails |
|----------|--------------|
| Answering about the content before transcribing | You cannot hear the file. Anything you say about it is invented. |
| A custom `ffmpeg`/`whisper`/`pydub` script in the sandbox | No model or GPU there, and long files are killed by the timeout or the OOM killer. |
| `ocr_file` / `doc_ingest` on audio | Those read images and PDFs, not sound. |
| Stopping at the first `partial: true` result | You would summarize only the first minutes of a meeting as if it were the whole of it. |
| `force=True` on a resume | It throws away the chunks already transcribed and starts over. |

## Step 1 — Transcribe

```
transcribe_audio(relative_path="uploads/<file>")
```

Use the path from the attachments block (`uploads/...`). If you do not know it, call
`sandbox_list_files(subdir="uploads")`.

**Language.** Leave `language` empty: the server applies the default configured by the
administrator. Pass an ISO code (`en`, `fr`, `de`, …) only when the user says the
recording is in another language, or when the first result is clearly garbled because
of a wrong language. Use `language="auto"` for unknown or mixed-language recordings.
After changing the language of a file already transcribed, call again with
`force=True`: otherwise the old chunks are reused.

## Step 2 — Long recordings: resume until done

Transcription runs in chunks within a time budget. When the result has
`partial: true`:

1. call `transcribe_audio` again with the **same** `relative_path` and
   `start_sec=<resume_from_sec>`;
2. repeat until `partial` is `false`;
3. on recordings longer than ~15 minutes, tell the user briefly how far you are
   (`transcribed_until_sec` vs `duration_sec`) between calls.

Chunks already on disk are skipped, so a repeated call never redoes work.

If a call ends with a **timeout** message, call it again with the same arguments and a
smaller `budget_sec` (e.g. `60`): completed chunks are kept.

If only one part of the recording matters ("what was decided at the end?"), transcribe
just that window with `start_sec` and `max_duration_sec` instead of the whole file.

## Step 3 — Read the transcript

The result is a JSON manifest:

* `text` — the full transcript, present when it is short. Use it directly.
* otherwise `excerpt` + `transcript_path` (`derived/audio/<slug>/transcript.txt`).
  Read it with `sandbox_read_file_chunk(relative_path=<transcript_path>, offset_lines=0, max_lines=500)`,
  page by page, before summarizing.
* to find a topic, a name or a number, search the per-chunk files with the
  `grep_hint` from the manifest:

```
sandbox_grep_content(
    pattern="<regex>",
    relative_root="derived",
    glob_filter="audio/<slug>/chunks/*.txt",
)
```

Every line starts with its `[mm:ss]` (or `[h:mm:ss]`) timestamp. Widen the pattern for
spoken variants and recognition errors (`[Bb]udget|bilancio|costi`), since speech
recognition often misspells proper names and technical terms.

## Step 4 — Answer

* Cite the timestamp of every fact, decision or quote you report: `[12:40]`.
* The transcript has **no speaker labels**. Do not attribute sentences to people unless
  the speakers name themselves or each other in the audio; otherwise write "someone says".
* Quote verbatim only what the transcript says; mark uncertain words as such
  (names, figures, acronyms are the most error-prone).
* Speech recognition may produce repeated or invented lines over silence or music: if
  a passage looks out of place, say so instead of using it.
* For minutes or summaries, cover the whole recording (all chunks), not only the
  beginning. Long outputs follow `artifact_protocol`.

## Errors

| `error` | What to do |
|---------|------------|
| `path_error` | Wrong path: list `uploads/` and retry with the exact name. |
| `not_audio` | The file has no audio track. If it is a PDF or image, use the document/OCR tools. |
| `too_large` / `too_long` | Above the server limits: transcribe a window with `start_sec` / `max_duration_sec`, or ask the user for a shorter file. |
| `empty_range` | `start_sec` is past the end: the recording is already fully transcribed. |
| `engine_failed` | The speech recognition service or model is not working. Tell the user that an administrator should check Settings → Audio; do not try workarounds. |
| `failed_chunks` not empty | Some chunks are missing: call `transcribe_audio` again with the same arguments to retry them before answering. |
| `warning: No speech recognised` | The range contains no speech (silence, music) or the language is wrong: say so, and retry with `language="auto"` if the user expects speech. |
