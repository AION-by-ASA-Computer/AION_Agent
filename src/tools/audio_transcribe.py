"""Chunked speech-to-text of session audio files into ``derived/audio/<slug>``.

Used by the ``stt`` MCP server (``mcp_servers_std/stt_mcp/server.py``) and meant
to be reusable by other callers (e.g. WhatsApp voice notes) that need the same
transcription without going through MCP.

Two engines, selected like the OCR server selects its backend:

* ``remote``: an OpenAI-compatible ``POST {AION_STT_BASE_URL}/audio/transcriptions``
  (Whisper on vLLM, speaches, OpenAI) when both ``AION_STT_BASE_URL`` and a real
  ``AION_STT_API_KEY`` are configured;
* ``local``: faster-whisper (Whisper on CTranslate2, CPU + int8) otherwise.

Audio is decoded with PyAV (bundled with faster-whisper, it ships its own FFmpeg
libraries) one chunk at a time, so a two-hour recording never sits in memory as
a whole. The artefact layout mirrors ``doc_ingest``: one text file per chunk
(``chunks/cNNNN.txt``) whose lines are ``[mm:ss] text``. Chunks already on disk
are skipped, and a run that hits ``budget_sec`` returns ``partial`` plus
``resume_from_sec`` instead of being killed by the MCP bridge timeout.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import math
import os
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator, Optional

import numpy as np

from src.tools.doc_ingest import slugify_document_name

__all__ = [
    "AUDIO_SUBDIR",
    "SAMPLE_RATE",
    "ChunkResult",
    "SttEngine",
    "DEFAULT_LOCAL_MODEL",
    "LOCAL_MODEL_CHOICES",
    "build_engine_from_env",
    "download_local_model",
    "find_local_model",
    "is_remote_stt_enabled",
    "local_model_name",
    "probe_audio_duration",
    "iter_audio_chunks",
    "load_audio_manifest",
    "STT_JOB_LOCK",
    "resolve_language",
    "transcribe_audio_file",
    "transcribe_audio_to_text",
]

logger = logging.getLogger("audio_transcribe")

AUDIO_SUBDIR = "derived/audio"

# Whisper (local and remote) works on 16 kHz mono; decoding straight to that
# format avoids a second resampling step inside the engines.
SAMPLE_RATE = 16000

_EXCERPT_CHARS = 400


@dataclass
class ChunkResult:
    """Transcription of one audio chunk.

    ``segments`` holds ``(start_sec, end_sec, text)`` tuples with times relative
    to the beginning of the chunk; the caller shifts them to absolute offsets.
    """

    segments: list[tuple[float, float, str]] = field(default_factory=list)
    language: Optional[str] = None
    language_probability: Optional[float] = None


# Engine callback: (float32 PCM at SAMPLE_RATE, language or None) -> ChunkResult.
TranscribeChunk = Callable[[np.ndarray, Optional[str]], Awaitable[ChunkResult]]


@dataclass
class SttEngine:
    """An engine ready to transcribe chunks.

    ``name`` is ``local`` or ``remote``; ``model`` is reported in the manifest so
    the agent (and whoever debugs a bad transcript) knows what produced it.
    """

    name: str
    model: str
    chunk_sec: float
    transcribe_chunk: TranscribeChunk


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name, "").strip()
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def is_remote_stt_enabled() -> bool:
    """True when the external STT service is configured.

    Same rule as the OCR server (``_is_advanced_ocr_enabled``): a base URL plus
    an API key that is not the ``EMPTY`` placeholder. Anything else falls back
    to the local faster-whisper engine.
    """
    base = os.environ.get("AION_STT_BASE_URL", "").strip()
    key = os.environ.get("AION_STT_API_KEY", "").strip()
    return bool(base) and bool(key) and key != "EMPTY"


def resolve_language(requested: str) -> Optional[str]:
    """Language code to pass to the engine, or ``None`` for auto-detection.

    An empty ``requested`` falls back to ``AION_STT_LANGUAGE`` (default ``it``,
    the deployment's primary language); ``auto`` at either level means detect.
    """
    lang = (requested or "").strip().lower()
    if not lang:
        lang = os.environ.get("AION_STT_LANGUAGE", "it").strip().lower()
    if not lang or lang == "auto":
        return None
    return lang


# ---------------------------------------------------------------------------
# Decoding (PyAV)
# ---------------------------------------------------------------------------


def probe_audio_duration(path: Path) -> Optional[float]:
    """Duration in seconds of the first audio stream, ``None`` when unknown.

    Raises ``ValueError`` when the file has no audio stream (e.g. a PDF or an
    image uploaded by mistake) so callers can report a clear error.
    """
    import av  # imported lazily: only needed when audio is actually processed

    with av.open(str(path), mode="r") as container:
        if not container.streams.audio:
            raise ValueError(f"{path.name} has no audio stream")
        stream = container.streams.audio[0]
        if stream.duration is not None and stream.time_base is not None:
            return float(stream.duration * stream.time_base)
        if container.duration is not None:
            # Container duration is expressed in av.time_base (microseconds).
            return float(container.duration) / 1_000_000
    # Some streamed formats (e.g. raw Ogg/Opus voice notes) carry no duration;
    # the chunk loop then simply decodes until EOF.
    return None


def iter_audio_chunks(
    path: Path, *, start_sec: float, chunk_sec: float, end_sec: Optional[float] = None
) -> Iterator[tuple[float, np.ndarray]]:
    """Yield ``(chunk_start_sec, float32 PCM)`` chunks of ``chunk_sec`` seconds.

    Decoding starts at ``start_sec`` (container seek + sample-accurate trim) and
    stops at ``end_sec`` or EOF. Audio is resampled to 16 kHz mono; the last
    chunk may be shorter. Blocking and CPU-bound: run it in a worker thread.
    """
    import av

    chunk_samples = max(1, int(round(chunk_sec * SAMPLE_RATE)))
    end_sample = (
        int(round((end_sec - start_sec) * SAMPLE_RATE)) if end_sec is not None else None
    )
    resampler = av.audio.resampler.AudioResampler(
        format="s16", layout="mono", rate=SAMPLE_RATE
    )
    pending: list[np.ndarray] = []
    pending_len = 0
    emitted = 0  # samples yielded so far, counted from start_sec

    def _take(n: int) -> np.ndarray:
        """Pop exactly ``n`` samples (or all that remain) from ``pending``."""
        nonlocal pending, pending_len
        buf = np.concatenate(pending) if len(pending) > 1 else pending[0]
        out, rest = buf[:n], buf[n:]
        pending = [rest] if rest.size else []
        pending_len = int(rest.size)
        return out

    with av.open(str(path), mode="r") as container:
        if not container.streams.audio:
            raise ValueError(f"{path.name} has no audio stream")
        stream = container.streams.audio[0]
        if start_sec > 0:
            # Seek lands on the packet at or before start_sec; the frames that
            # precede it are trimmed below using their presentation time.
            container.seek(int(start_sec * 1_000_000), any_frame=False, backward=True)

        def _resampled() -> Iterator[np.ndarray]:
            for frame in container.decode(stream):
                frame_time = frame.time
                drop = 0
                if frame_time is not None and frame_time < start_sec:
                    frame_end = frame_time + frame.samples / float(frame.sample_rate)
                    if frame_end <= start_sec:
                        continue
                    drop = int(round((start_sec - frame_time) * SAMPLE_RATE))
                for out in resampler.resample(frame):
                    arr = out.to_ndarray().reshape(-1)
                    if drop:
                        arr, drop = arr[drop:], max(0, drop - arr.size)
                    if arr.size:
                        yield arr
            # Flush samples still buffered inside the resampler.
            for out in resampler.resample(None):
                arr = out.to_ndarray().reshape(-1)
                if arr.size:
                    yield arr

        for arr in _resampled():
            pending.append(arr)
            pending_len += int(arr.size)
            while pending_len >= chunk_samples:
                want = chunk_samples
                if end_sample is not None:
                    want = min(want, end_sample - emitted)
                    if want <= 0:
                        return
                chunk = _take(want)
                yield (
                    start_sec + emitted / SAMPLE_RATE,
                    chunk.astype(np.float32) / 32768.0,
                )
                emitted += int(chunk.size)
                if end_sample is not None and emitted >= end_sample:
                    return

        if pending_len:
            want = pending_len
            if end_sample is not None:
                want = min(want, end_sample - emitted)
            if want > 0:
                chunk = _take(want)
                yield (
                    start_sec + emitted / SAMPLE_RATE,
                    chunk.astype(np.float32) / 32768.0,
                )


def _pcm_to_wav_bytes(pcm: np.ndarray) -> bytes:
    """Encode float32 PCM as a 16-bit mono WAV file in memory (remote upload)."""
    clipped = np.clip(pcm, -1.0, 1.0)
    ints = (clipped * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(ints.tobytes())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------

# One WhisperModel per worker process: loading `small` takes seconds and ~1 GB,
# so it is cached for the lifetime of the (session-scoped) MCP worker.
_LOCAL_MODEL_CACHE: dict[tuple[str, str, int, str], Any] = {}
_LOCAL_MODEL_LOCK = threading.Lock()

# One in-process STT job at a time (WhatsApp voice notes, chat dictation): the
# local model above is shared and CPU-bound, the remote service usually a single
# GPU. A plain asyncio lock is enough because the backend runs ``--workers 1``.
STT_JOB_LOCK = asyncio.Lock()


# Multilingual faster-whisper sizes offered in admin-ui, smallest first. The
# English-only variants (``*.en``, ``distil-*``) are left out on purpose: the
# deployments transcribe Italian. ``AION_STT_LOCAL_MODEL`` still accepts any
# other faster-whisper name or a model directory.
LOCAL_MODEL_CHOICES = ("tiny", "base", "small", "medium", "large-v3-turbo", "large-v3")

DEFAULT_LOCAL_MODEL = "small"


def local_model_name() -> str:
    """Configured local model (``AION_STT_LOCAL_MODEL``), ``small`` when unset."""
    return os.environ.get("AION_STT_LOCAL_MODEL", "").strip() or DEFAULT_LOCAL_MODEL


def local_model_download_dir() -> Path:
    """Where models missing on disk are downloaded: the persistent data volume.

    Downloads never go to ``AION_STT_LOCAL_MODEL_DIR``: in Docker that is a path
    inside the image, so a model fetched there at runtime would be lost every
    time the container is recreated.
    """
    from src.session_workspace import data_root

    return data_root() / "models" / "faster-whisper"


def local_model_search_dirs() -> list[Path]:
    """Directories holding ``<name>/model.bin``, in lookup order.

    ``AION_STT_LOCAL_MODEL_DIR`` (models baked into the Docker image at build
    time) comes first, then the download directory.
    """
    dirs: list[Path] = []
    baked = os.environ.get("AION_STT_LOCAL_MODEL_DIR", "").strip()
    if baked:
        dirs.append(Path(baked))
    download_dir = local_model_download_dir()
    if download_dir not in dirs:
        dirs.append(download_dir)
    return dirs


def find_local_model(model_name: str) -> Optional[Path]:
    """Directory of an already available model, or None if it must be downloaded."""
    if Path(model_name).is_dir():
        return Path(model_name)
    for root in local_model_search_dirs():
        if (root / model_name / "model.bin").is_file():
            return root / model_name
    return None


def download_local_model(model_name: str) -> Path:
    """Download a faster-whisper model into the persistent data directory.

    Blocking (hundreds of MB to a few GB from Hugging Face). Called on first use
    by the engine and ahead of time by the admin API, so the first transcription
    does not spend its time budget on the download.
    """
    from faster_whisper import download_model

    target = local_model_download_dir() / model_name
    logger.info("Downloading faster-whisper model %s into %s", model_name, target)
    return Path(download_model(model_name, output_dir=str(target)))


def _resolve_local_model_path(model_name: str) -> str:
    """Directory of the CTranslate2 model, downloading it on first use."""
    found = find_local_model(model_name)
    return str(found if found is not None else download_local_model(model_name))


def _load_local_model(model_name: str, compute_type: str, cpu_threads: int):
    """Load (or reuse) the faster-whisper model for this worker process."""
    key = (model_name, compute_type, cpu_threads)
    with _LOCAL_MODEL_LOCK:
        model = _LOCAL_MODEL_CACHE.get(key)
        if model is None:
            from faster_whisper import WhisperModel

            path = _resolve_local_model_path(model_name)
            logger.info(
                "Loading faster-whisper model %s (compute_type=%s, cpu_threads=%s)",
                path,
                compute_type,
                cpu_threads,
            )
            model = WhisperModel(
                path,
                device="cpu",
                compute_type=compute_type,
                cpu_threads=cpu_threads,
            )
            _LOCAL_MODEL_CACHE[key] = model
        return model


def _local_engine() -> SttEngine:
    """faster-whisper engine configured from ``AION_STT_LOCAL_*``."""
    import asyncio

    model_name = local_model_name()
    compute_type = os.environ.get("AION_STT_LOCAL_COMPUTE_TYPE", "").strip() or "int8"
    cpu_threads = max(0, _env_int("AION_STT_LOCAL_CPU_THREADS", 0))
    beam_size = max(1, _env_int("AION_STT_LOCAL_BEAM_SIZE", 5))

    def _run(pcm: np.ndarray, language: Optional[str]) -> ChunkResult:
        model = _load_local_model(model_name, compute_type, cpu_threads)
        # vad_filter drops silence before decoding: faster on voice notes and it
        # suppresses Whisper's typical hallucinations on silent stretches.
        segments, info = model.transcribe(
            pcm, language=language, beam_size=beam_size, vad_filter=True
        )
        # `segments` is a lazy generator: decoding actually happens here.
        out = [(float(s.start), float(s.end), s.text.strip()) for s in segments]
        return ChunkResult(
            segments=[s for s in out if s[2]],
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
        )

    async def transcribe_chunk(pcm: np.ndarray, language: Optional[str]) -> ChunkResult:
        return await asyncio.to_thread(_run, pcm, language)

    return SttEngine(
        name="local",
        model=model_name,
        # Longer than the remote chunk: fewer words cut at chunk boundaries, and
        # faster-whisper already windows the audio in 30 s internally.
        chunk_sec=max(5.0, _env_float("AION_STT_LOCAL_CHUNK_SEC", 60.0)),
        transcribe_chunk=transcribe_chunk,
    )


def _remote_engine(client: Any = None) -> SttEngine:
    """OpenAI-compatible ``/audio/transcriptions`` engine (``AION_STT_*``).

    ``client`` is an optional ``httpx.AsyncClient`` (tests inject one with a
    mock transport); otherwise a client is opened per chunk.
    """
    import httpx

    base = os.environ.get("AION_STT_BASE_URL", "").strip().rstrip("/")
    model = os.environ.get("AION_STT_MODEL", "").strip() or "openai/whisper-large-v3"
    key = os.environ.get("AION_STT_API_KEY", "EMPTY").strip()
    timeout = _env_float("AION_STT_TIMEOUT", 120.0)

    async def transcribe_chunk(pcm: np.ndarray, language: Optional[str]) -> ChunkResult:
        data = {"model": model, "response_format": "json"}
        if language:
            data["language"] = language
        files = {"file": ("chunk.wav", _pcm_to_wav_bytes(pcm), "audio/wav")}
        headers = {"Authorization": f"Bearer {key}"}
        url = f"{base}/audio/transcriptions"
        try:
            if client is not None:
                r = await client.post(url, data=data, files=files, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=timeout) as c:
                    r = await c.post(url, data=data, files=files, headers=headers)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"HTTP {e.response.status_code} from STT server: {e.response.text[:500]}"
            ) from e
        try:
            payload = r.json()
            text = (
                payload.get("text", "") if isinstance(payload, dict) else str(payload)
            )
        except ValueError:
            # response_format=json is requested, but some servers answer text/plain.
            text = r.text
        text = (text or "").strip()
        duration = pcm.size / SAMPLE_RATE
        # The plain json format has no segment timestamps: the whole chunk is one
        # segment, which is why remote chunks are kept short (default 30 s).
        return ChunkResult(
            segments=[(0.0, duration, text)] if text else [], language=language
        )

    return SttEngine(
        name="remote",
        model=model,
        chunk_sec=max(5.0, _env_float("AION_STT_CHUNK_SEC", 30.0)),
        transcribe_chunk=transcribe_chunk,
    )


def build_engine_from_env(client: Any = None) -> SttEngine:
    """Pick the remote engine when configured, else local faster-whisper."""
    if is_remote_stt_enabled():
        return _remote_engine(client)
    return _local_engine()


# ---------------------------------------------------------------------------
# Chunk loop
# ---------------------------------------------------------------------------


def _chunk_filename(index: int) -> str:
    return f"c{index:04d}.txt"


def _fmt_ts(seconds: float) -> str:
    """``mm:ss`` (or ``h:mm:ss`` past one hour) for transcript line prefixes."""
    total = int(max(0.0, seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _rebuild_transcript(chunks_dir: Path, transcript_path: Path) -> str:
    """Concatenate every chunk file in order into ``transcript.txt``."""
    parts = []
    for chunk_file in sorted(chunks_dir.glob("c*.txt")):
        body = chunk_file.read_text(encoding="utf-8", errors="replace").strip()
        if body:
            parts.append(body)
    text = "\n".join(parts)
    transcript_path.write_text(text + ("\n" if text else ""), encoding="utf-8")
    return text


def _error(code: str, message: str, hint: str = "") -> dict:
    out = {"ok": False, "error": code, "message": message}
    if hint:
        out["hint"] = hint
    return out


async def transcribe_audio_file(
    src_path: Path,
    session_root: Path,
    *,
    engine: SttEngine,
    language: Optional[str] = None,
    start_sec: float = 0.0,
    max_duration_sec: float = 0.0,
    budget_sec: float = 90.0,
    force: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Transcribe ``src_path`` into ``<session_root>/derived/audio/<slug>``.

    Returns a JSON-serialisable manifest (also written to ``manifest.json``).
    ``max_duration_sec`` limits how much audio after ``start_sec`` is processed
    (0 = until the end). Chunks already transcribed are reused unless ``force``.
    """
    import asyncio

    started = clock()

    if not src_path.is_file():
        return _error("not_a_file", f"{src_path.name} is not a readable file")

    max_bytes = _env_int("AION_STT_MAX_AUDIO_BYTES", 100 * 1024 * 1024)
    size = src_path.stat().st_size
    if size > max_bytes:
        return _error(
            "too_large",
            f"{src_path.name} is {size} bytes, above AION_STT_MAX_AUDIO_BYTES={max_bytes}",
        )

    try:
        duration = await asyncio.to_thread(probe_audio_duration, src_path)
    except ImportError:
        return _error(
            "decoder_unavailable",
            "PyAV is not installed",
            "Install the backend requirements (faster-whisper pulls in 'av').",
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the model as JSON
        return _error(
            "not_audio",
            f"Cannot read audio from {src_path.name}: {exc}",
            "transcribe_audio accepts audio files (mp3, wav, ogg/opus, m4a, flac, "
            "webm) or videos with an audio track. Use ocr_file/doc_ingest for "
            "images and PDFs.",
        )

    max_total = _env_float("AION_STT_MAX_DURATION_SEC", 7200.0)
    if duration is not None and max_total > 0 and duration > max_total:
        return _error(
            "too_long",
            f"{src_path.name} lasts {duration:.0f}s, above "
            f"AION_STT_MAX_DURATION_SEC={max_total:.0f}",
            "Transcribe a window with start_sec/max_duration_sec.",
        )

    chunk_sec = engine.chunk_sec
    start_sec = max(0.0, float(start_sec or 0.0))
    if duration is not None and start_sec >= duration:
        return _error(
            "empty_range",
            f"start_sec={start_sec:.0f} is past the end of the audio ({duration:.0f}s)",
        )
    end_sec: Optional[float] = None
    if max_duration_sec and max_duration_sec > 0:
        end_sec = start_sec + float(max_duration_sec)
    if duration is not None:
        end_sec = duration if end_sec is None else min(end_sec, duration)

    slug = slugify_document_name(src_path.name)
    root = session_root / AUDIO_SUBDIR / slug
    chunks_dir = root / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"

    # Chunk files are indexed by position, so they are only reusable when the
    # chunk length is the same as the run that wrote them (switching between the
    # local and remote engine changes it). Otherwise start over.
    if manifest_path.is_file() and not force:
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            if float(previous.get("chunk_sec", chunk_sec)) != chunk_sec:
                force = True
        except (ValueError, OSError):
            force = True
    if force:
        for old in chunks_dir.glob("c*.txt"):
            old.unlink()

    # Align to the chunk grid so a resume re-enters exactly where the previous
    # run stopped and chunk files line up with their index.
    first_index = int(start_sec // chunk_sec)
    aligned_start = first_index * chunk_sec
    last_index: Optional[int] = None
    if end_sec is not None:
        last_index = max(first_index, math.ceil(end_sec / chunk_sec) - 1)

    # Jump over the leading chunks already on disk so they are not even decoded.
    index = first_index
    while (chunks_dir / _chunk_filename(index)).is_file() and (
        last_index is None or index <= last_index
    ):
        index += 1
    skipped = index - first_index

    written = 0
    partial = False
    resume_from_sec: Optional[float] = None
    detected_language: Optional[str] = None
    language_probability: Optional[float] = None
    failed_chunks: list[int] = []
    slowest_chunk = 0.0
    transcribed_until = index * chunk_sec

    if last_index is None or index <= last_index:
        chunks = iter_audio_chunks(
            src_path, start_sec=index * chunk_sec, chunk_sec=chunk_sec, end_sec=end_sec
        )
        try:
            while last_index is None or index <= last_index:
                # Stop before a chunk that would likely overrun the budget, using
                # the slowest chunk seen so far as the estimate: the MCP bridge
                # kills the call at AION_MCP_TOOL_RESULT_TIMEOUT otherwise.
                elapsed = clock() - started
                if elapsed >= budget_sec or (
                    slowest_chunk and elapsed + slowest_chunk > budget_sec
                ):
                    partial = True
                    resume_from_sec = index * chunk_sec
                    break
                item = await asyncio.to_thread(next, chunks, None)
                if item is None:
                    break
                chunk_start, pcm = item
                target = chunks_dir / _chunk_filename(index)
                if target.is_file():
                    # A later chunk survived from an earlier run (gap filled now).
                    skipped += 1
                else:
                    t0 = clock()
                    try:
                        result = await engine.transcribe_chunk(pcm, language)
                        lines = [
                            f"[{_fmt_ts(chunk_start + s)}] {text}"
                            for s, _e, text in result.segments
                        ]
                        target.write_text("\n".join(lines), encoding="utf-8")
                        written += 1
                        if result.language and not detected_language:
                            detected_language = result.language
                            language_probability = result.language_probability
                    except Exception as exc:  # noqa: BLE001 - keep going, report it
                        # No chunk file is written, so the next call retries it.
                        logger.warning("STT failed on chunk %d: %s", index, exc)
                        failed_chunks.append(index)
                        if len(failed_chunks) == 1 and written == 0:
                            # The very first chunk failed: most likely the model
                            # or the service is unusable, so fail fast.
                            return _error(
                                "engine_failed",
                                f"{engine.name} STT failed: {exc}",
                                _engine_hint(engine),
                            )
                    slowest_chunk = max(slowest_chunk, clock() - t0)
                transcribed_until = chunk_start + pcm.size / SAMPLE_RATE
                index += 1
        finally:
            chunks.close()

    if end_sec is not None:
        transcribed_until = min(transcribed_until, end_sec)

    transcript_path = root / "transcript.txt"
    text = _rebuild_transcript(chunks_dir, transcript_path)
    rel_root = f"{AUDIO_SUBDIR}/{slug}"
    inline_max = _env_int("AION_STT_INLINE_MAX_CHARS", 8000)

    manifest: dict[str, Any] = {
        "ok": True,
        "slug": slug,
        "source": src_path.name,
        "engine": engine.name,
        "model": engine.model,
        "language": language or detected_language,
        "language_detected": detected_language,
        "language_probability": (
            round(language_probability, 3) if language_probability is not None else None
        ),
        "duration_sec": round(duration, 2) if duration is not None else None,
        "chunk_sec": chunk_sec,
        "range_sec": [aligned_start, end_sec],
        "chunks_written": written,
        "chunks_skipped_existing": skipped,
        "failed_chunks": failed_chunks,
        "transcribed_until_sec": round(transcribed_until, 2),
        "partial": partial,
        "resume_from_sec": resume_from_sec,
        "root": rel_root,
        "transcript_path": f"{rel_root}/transcript.txt",
        "chars": len(text),
        "grep_hint": (
            "sandbox_grep_content(pattern=<regex>, relative_root='derived', "
            f"glob_filter='audio/{slug}/chunks/*.txt') — each line starts with its "
            "[mm:ss] timestamp."
        ),
    }
    if len(text) <= inline_max:
        manifest["text"] = text
    else:
        manifest["excerpt"] = text[:_EXCERPT_CHARS]
    if not text.strip() and not partial:
        manifest["warning"] = "No speech recognised in the processed range."
    if failed_chunks:
        manifest["warning"] = (
            f"{len(failed_chunks)} chunk(s) failed and are missing from the "
            "transcript; call transcribe_audio again to retry them."
        )
    if partial:
        manifest["next_step"] = (
            f"Budget of {budget_sec:.0f}s reached at {_fmt_ts(resume_from_sec or 0)}. "
            f"Call transcribe_audio again with start_sec={resume_from_sec:.0f} to "
            "resume; chunks already transcribed are skipped."
        )

    manifest_path.write_text(
        json.dumps(
            {k: v for k, v in manifest.items() if k != "text"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest


def load_audio_manifest(session_root: Path, filename: str) -> Optional[dict]:
    """Manifest of a previous transcription of ``filename``, ``None`` if absent.

    Same slug as ``transcribe_audio_file``. Used by the agent pipeline to tell
    the model an attachment is already transcribed (e.g. WhatsApp voice notes,
    transcribed before the turn) instead of asking it to call the tool again.
    """
    path = session_root / AUDIO_SUBDIR / slugify_document_name(filename) / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


async def transcribe_audio_to_text(
    src_path: Path,
    *,
    engine: SttEngine,
    language: Optional[str] = None,
    max_duration_sec: float = 0.0,
) -> dict:
    """Transcribe a short clip straight to text, writing nothing to disk.

    Meant for chat dictation (``POST /v1/voice/transcribe``): segments are joined
    with spaces and carry no ``[mm:ss]`` prefix, and nothing lands in the session
    workspace. ``max_duration_sec`` (0 = no limit) rejects longer clips with
    ``too_long``; clips without a duration header (browser WebM recordings) are
    decoded up to that limit and no further.
    """
    if not src_path.is_file():
        return _error("not_a_file", f"{src_path.name} is not a readable file")

    try:
        duration = await asyncio.to_thread(probe_audio_duration, src_path)
    except ImportError:
        return _error("decoder_unavailable", "PyAV is not installed")
    except Exception as exc:  # noqa: BLE001 - reported to the caller as JSON
        return _error("not_audio", f"Cannot read audio from {src_path.name}: {exc}")

    limit = float(max_duration_sec or 0.0)
    if limit > 0 and duration is not None and duration > limit:
        return _error(
            "too_long", f"{src_path.name} lasts {duration:.0f}s, above the {limit:.0f}s limit"
        )

    end_sec = limit if limit > 0 else None
    parts: list[str] = []
    detected_language: Optional[str] = None
    decoded_sec = 0.0
    chunks = iter_audio_chunks(
        src_path, start_sec=0.0, chunk_sec=engine.chunk_sec, end_sec=end_sec
    )
    try:
        while True:
            item = await asyncio.to_thread(next, chunks, None)
            if item is None:
                break
            chunk_start, pcm = item
            decoded_sec = chunk_start + pcm.size / SAMPLE_RATE
            try:
                result = await engine.transcribe_chunk(pcm, language)
            except Exception as exc:  # noqa: BLE001 - no partial text for dictation
                logger.warning("Dictation STT failed: %s", exc)
                return _error(
                    "engine_failed", f"{engine.name} STT failed: {exc}", _engine_hint(engine)
                )
            parts.extend(text for _s, _e, text in result.segments if text)
            if result.language and not detected_language:
                detected_language = result.language
    except Exception as exc:  # noqa: BLE001 - corrupt stream mid-way
        return _error("not_audio", f"Cannot decode {src_path.name}: {exc}")
    finally:
        chunks.close()

    text = " ".join(parts).strip()
    if not text:
        return _error("empty", "No speech recognised in the recording.")
    return {
        "ok": True,
        "text": text,
        "language": language or detected_language,
        "duration_sec": round(duration if duration is not None else decoded_sec, 2),
        "engine": engine.name,
        "model": engine.model,
    }


def _engine_hint(engine: SttEngine) -> str:
    """Operator-facing hint for a failing engine, returned with the error."""
    if engine.name == "remote":
        return (
            "Check AION_STT_BASE_URL / AION_STT_API_KEY / AION_STT_MODEL: the "
            "service must expose POST /audio/transcriptions."
        )
    return (
        "Check that faster-whisper is installed and AION_STT_LOCAL_MODEL points to a "
        "model name or a downloaded CTranslate2 model directory (first use downloads "
        "it into AION_STT_LOCAL_MODEL_DIR)."
    )
