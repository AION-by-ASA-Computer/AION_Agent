"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { fetchVoiceStatus, transcribeVoice, VoiceTranscribeError } from "@/lib/api/aion";
import { getLocale } from "@/lib/i18n/i18n-store";

export type VoiceDictationState = "idle" | "requesting" | "recording" | "transcribing";

/** i18n key suffix under ``chat.voice.*`` for the last error. */
export type VoiceDictationError =
  | "permission_denied"
  | "no_microphone"
  | "too_long"
  | "too_large"
  | "empty"
  | "failed";

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return undefined;
  }
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m));
}

/** Microphone recording is only possible in a secure context (HTTPS or localhost). */
function browserCanRecord(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    typeof navigator.mediaDevices?.getUserMedia === "function" &&
    typeof MediaRecorder !== "undefined"
  );
}

function errorFromException(err: unknown): VoiceDictationError {
  if (err instanceof VoiceTranscribeError) {
    if (err.code === "too_long" || err.code === "too_large" || err.code === "empty") return err.code;
    return "failed";
  }
  const name = (err as { name?: string } | null)?.name;
  if (name === "NotAllowedError" || name === "SecurityError") return "permission_denied";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "no_microphone";
  return "failed";
}

/**
 * Dictation for the chat composer: record from the microphone, send the clip to
 * ``POST /v1/voice/transcribe`` and hand the text to ``onTranscript``. The
 * recording never becomes a session upload, so it is not attached to the chat.
 */
export function useVoiceDictation(
  userId: string,
  token: string | null | undefined,
  onTranscript: (text: string) => void,
) {
  const [supported, setSupported] = useState(false);
  const [maxSeconds, setMaxSeconds] = useState(0);
  const [state, setState] = useState<VoiceDictationState>("idle");
  const [elapsedSec, setElapsedSec] = useState(0);
  const [error, setError] = useState<VoiceDictationError | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const discardRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const onTranscriptRef = useRef(onTranscript);
  useEffect(() => {
    onTranscriptRef.current = onTranscript;
  }, [onTranscript]);

  useEffect(() => {
    // ``supported`` stays false (its initial value) without a usable microphone.
    if (!browserCanRecord() || !userId) return;
    let alive = true;
    void fetchVoiceStatus(userId, token).then((s) => {
      if (!alive) return;
      setSupported(s.enabled);
      setMaxSeconds(s.max_duration_sec);
    });
    return () => {
      alive = false;
    };
  }, [userId, token]);

  const releaseMicrophone = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const transcribe = useCallback(
    async (audio: Blob) => {
      setState("transcribing");
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        const text = await transcribeVoice(audio, { language: getLocale(), signal: ctrl.signal }, userId, token);
        if (text) onTranscriptRef.current(text);
        else setError("empty");
      } catch (err) {
        if (!ctrl.signal.aborted) setError(errorFromException(err));
      } finally {
        if (abortRef.current === ctrl) abortRef.current = null;
        setState("idle");
      }
    },
    [userId, token],
  );

  const stop = useCallback(() => {
    const rec = recorderRef.current;
    if (rec && rec.state !== "inactive") rec.stop();
  }, []);

  const cancel = useCallback(() => {
    discardRef.current = true;
    stop();
    abortRef.current?.abort();
  }, [stop]);

  const start = useCallback(async () => {
    if (state !== "idle") return;
    setError(null);
    setState("requesting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setError(errorFromException(err));
      setState("idle");
      return;
    }
    streamRef.current = stream;
    chunksRef.current = [];
    discardRef.current = false;
    const mimeType = pickMimeType();
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorderRef.current = rec;
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    rec.onstop = () => {
      releaseMicrophone();
      recorderRef.current = null;
      const audio = new Blob(chunksRef.current, { type: rec.mimeType || mimeType || "audio/webm" });
      chunksRef.current = [];
      if (discardRef.current || audio.size === 0) {
        setState("idle");
        return;
      }
      void transcribe(audio);
    };
    rec.start(1000);
    setElapsedSec(0);
    setState("recording");
    const startedAt = Date.now();
    timerRef.current = setInterval(() => {
      const secs = Math.floor((Date.now() - startedAt) / 1000);
      setElapsedSec(secs);
      // Stop a little before the backend limit so the clip is never rejected.
      if (maxSeconds > 0 && secs >= maxSeconds - 1) stop();
    }, 250);
  }, [state, maxSeconds, releaseMicrophone, transcribe, stop]);

  // Unmount (e.g. switching conversation): drop the recording and free the mic.
  useEffect(
    () => () => {
      discardRef.current = true;
      const rec = recorderRef.current;
      if (rec && rec.state !== "inactive") rec.stop();
      abortRef.current?.abort();
      releaseMicrophone();
    },
    [releaseMicrophone],
  );

  return {
    supported,
    state,
    elapsedSec,
    maxSeconds,
    error,
    clearError: useCallback(() => setError(null), []),
    start,
    stop,
    cancel,
  };
}
