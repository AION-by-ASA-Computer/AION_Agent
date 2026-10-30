"use client";

import { Loader2, Mic, Square, X } from "lucide-react";

import type { VoiceDictationState } from "@/hooks/use-voice-dictation";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

function formatElapsed(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Composer microphone: idle → recording (timer, stop/cancel) → transcribing. */
export function VoiceInputButton({
  state,
  elapsedSec,
  disabled,
  onStart,
  onStop,
  onCancel,
}: {
  state: VoiceDictationState;
  elapsedSec: number;
  disabled?: boolean;
  onStart: () => void;
  onStop: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const recording = state === "recording";
  const busy = state === "requesting" || state === "transcribing";

  return (
    <div className="flex items-center gap-1">
      {recording && (
        <>
          <button
            type="button"
            onClick={onCancel}
            title={t("chat.voice.cancel")}
            aria-label={t("chat.voice.cancel")}
            className="focus-ring inline-flex size-7 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground cursor-pointer"
          >
            <X size={13} aria-hidden />
          </button>
          <span
            className="flex items-center gap-1.5 px-1 text-[0.786em] font-medium tabular-nums text-destructive"
            aria-live="polite"
          >
            <span className="size-2 rounded-full bg-destructive animate-pulse" aria-hidden />
            {formatElapsed(elapsedSec)}
          </span>
        </>
      )}
      <button
        type="button"
        onClick={recording ? onStop : onStart}
        disabled={busy || (!recording && disabled)}
        aria-pressed={recording}
        aria-label={
          recording
            ? t("chat.voice.stop")
            : state === "transcribing"
              ? t("chat.voice.transcribing")
              : t("chat.voice.start")
        }
        title={
          recording
            ? t("chat.voice.stop")
            : state === "transcribing"
              ? t("chat.voice.transcribing")
              : t("chat.voice.start")
        }
        className={cn(
          "focus-ring inline-flex size-9 sm:size-9.5 items-center justify-center rounded-full transition-all duration-200",
          recording
            ? "bg-destructive/20 text-destructive hover:scale-105 hover:bg-destructive/30 active:scale-95 cursor-pointer"
            : busy
              ? "bg-muted text-muted-foreground cursor-wait"
              : disabled
                ? "text-muted-foreground/40 opacity-40 cursor-not-allowed"
                : "text-muted-foreground hover:bg-muted hover:text-foreground active:scale-95 cursor-pointer",
        )}
      >
        {recording ? (
          <Square size={13} aria-hidden fill="currentColor" />
        ) : busy ? (
          <Loader2 size={15} aria-hidden className="animate-spin" />
        ) : (
          <Mic size={16} aria-hidden />
        )}
      </button>
    </div>
  );
}
