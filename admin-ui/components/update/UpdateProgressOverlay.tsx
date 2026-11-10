"use client";

/**
 * Full-screen progress view of a running AION upgrade.
 *
 * Mounted once in `AppShell`. It opens when:
 * - `UpdateConfirmDialog` fires `UPDATE_STARTED_EVENT`, or
 * - on page load the sidecar reports an upgrade already running (page reload,
 *   another admin started it), so everyone sees the same progress.
 *
 * While open it polls `GET /admin/update/status` every few seconds. Backend,
 * admin-ui and Caddy restart at every hop, so network errors and 502s are
 * expected: they are shown as "services restarting" and polling continues.
 * On success the page reloads (the admin-ui itself has a new version); on
 * failure the error is shown with a "Retry" that resumes from the failed hop
 * (install.sh resumes from AION_VERSION in .env).
 */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Circle, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/cn";
import { ghostBtn, outlineBtn, solidBtn } from "@/components/ui/classes";
import { useT } from "@/lib/i18n/use-t";
import {
  fetchUpdateStatus,
  startUpdate,
  UPDATE_STARTED_EVENT,
  type UpdateStartError,
  type UpdateStatus,
} from "@/lib/update";

// Poll interval: a hop takes minutes, 3s keeps the view lively without load.
const POLL_MS = 3000;
// Delay before reloading after success, so the admin can read the outcome.
const RELOAD_DELAY_MS = 3000;
const KNOWN_PHASES = ["starting", "plan", "backup", "fetch", "build", "pull", "migrate", "restart", "health", "done"];

/** "mm:ss" (or "h:mm:ss") since `startedAt`; empty when unknown. */
function formatElapsed(startedAt: string | undefined, now: number): string {
  if (!startedAt) return "";
  const start = Date.parse(startedAt);
  if (!Number.isFinite(start)) return "";
  const total = Math.max(0, Math.floor((now - start) / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export function UpdateProgressOverlay() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  // True while the last poll failed: the stack is restarting between phases.
  const [unreachable, setUnreachable] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const state = status?.state;
  const finished = state === "succeeded" || state === "failed";

  const poll = useCallback(async () => {
    const next = await fetchUpdateStatus();
    if (next && next.supported) {
      setStatus(next);
      setUnreachable(false);
    } else {
      setUnreachable(true);
    }
  }, []);

  // On mount: show the overlay only if an upgrade is already running.
  useEffect(() => {
    let active = true;
    void fetchUpdateStatus().then((s) => {
      if (active && s?.supported && s.state === "running") {
        setStatus(s);
        setOpen(true);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  // Open on the event fired by the confirmation dialog.
  useEffect(() => {
    const onStarted = (e: Event) => {
      const detail = (e as CustomEvent<UpdateStatus | undefined>).detail;
      if (detail) setStatus(detail);
      setRetryError(null);
      setOpen(true);
    };
    window.addEventListener(UPDATE_STARTED_EVENT, onStarted);
    return () => window.removeEventListener(UPDATE_STARTED_EVENT, onStarted);
  }, []);

  // Poll the status (and tick the elapsed timer) while the upgrade runs.
  useEffect(() => {
    if (!open || finished) return;
    const pollTimer = setInterval(() => void poll(), POLL_MS);
    const tickTimer = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearInterval(pollTimer);
      clearInterval(tickTimer);
    };
  }, [open, finished, poll]);

  // Success: reload to load the new admin-ui build.
  useEffect(() => {
    if (!open || state !== "succeeded") return;
    const timer = setTimeout(() => window.location.reload(), RELOAD_DELAY_MS);
    return () => clearTimeout(timer);
  }, [open, state]);

  const retry = async () => {
    setRetrying(true);
    setRetryError(null);
    try {
      setStatus(await startUpdate());
    } catch (err) {
      const e = err as UpdateStartError;
      if (e.code === "upgrade_running") {
        await poll();
      } else if (e.code === "no_update") {
        // Nothing left to apply (e.g. fixed by hand): treat as done.
        window.location.reload();
      } else {
        setRetryError(e.message || t("update.confirm.error_generic"));
      }
    } finally {
      setRetrying(false);
    }
  };

  if (!open) return null;

  const chain = status?.chain ?? [];
  const completed = new Set(status?.completed ?? []);
  const phase = status?.phase && KNOWN_PHASES.includes(status.phase) ? status.phase : "starting";
  const elapsed = formatElapsed(status?.started_at, now);
  const logTail = status?.log_tail ?? [];

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="update-overlay-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm"
    >
      <div className="flex max-h-[calc(100vh-2rem)] w-full max-w-lg flex-col gap-5 overflow-y-auto rounded-3xl border border-border bg-card p-6 shadow-2xl">
        {/* Header: outcome icon + title */}
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl",
              state === "succeeded" && "bg-emerald-500/10 text-emerald-500",
              state === "failed" && "bg-destructive/10 text-destructive",
              !finished && "bg-primary/10 text-primary",
            )}
          >
            {state === "succeeded" ? (
              <CheckCircle2 className="h-6 w-6" aria-hidden />
            ) : state === "failed" ? (
              <AlertTriangle className="h-6 w-6" aria-hidden />
            ) : (
              <Loader2 className="h-6 w-6 animate-spin" aria-hidden />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="update-overlay-title" className="text-lg font-semibold tracking-[-0.015em]">
              {state === "succeeded"
                ? t("update.progress.title_succeeded")
                : state === "failed"
                  ? t("update.progress.title_failed")
                  : t("update.progress.title_running")}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground" aria-live="polite">
              {state === "succeeded"
                ? t("update.progress.reloading")
                : state === "failed"
                  ? status?.error || t("update.confirm.error_generic")
                  : unreachable
                    ? t("update.progress.services_restarting")
                    : t(`update.progress.phase.${phase}`)}
            </p>
          </div>
          {elapsed && (
            <span className="shrink-0 rounded-full bg-secondary/80 px-2.5 py-1 font-mono text-xs text-muted-foreground">
              {elapsed}
            </span>
          )}
        </div>

        {/* Hop list with per-hop state */}
        {chain.length > 0 && (
          <ol className="flex flex-col gap-1.5 text-sm">
            {chain.map((version) => {
              const done = completed.has(version);
              const current = !done && status?.hop_to === version && !finished;
              const failedHere = !done && status?.hop_to === version && state === "failed";
              return (
                <li key={version} className="flex items-center gap-2.5">
                  {done ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-hidden />
                  ) : current ? (
                    <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden />
                  ) : failedHere ? (
                    <AlertTriangle className="h-4 w-4 text-destructive" aria-hidden />
                  ) : (
                    <Circle className="h-4 w-4 text-muted-foreground/50" aria-hidden />
                  )}
                  <span className={cn("font-mono", !done && !current && "text-muted-foreground")}>{version}</span>
                  <span className="text-xs text-muted-foreground">
                    {done
                      ? t("update.progress.hop_done")
                      : current
                        ? t("update.progress.hop_running")
                        : failedHere
                          ? t("update.progress.hop_failed")
                          : t("update.progress.hop_pending")}
                  </span>
                </li>
              );
            })}
          </ol>
        )}

        {state === "failed" && (
          <div className="flex flex-col gap-1 text-sm text-muted-foreground">
            <p>{t("update.progress.failed_hint")}</p>
            {status?.backup && <p>{t("update.progress.backup_hint", { path: status.backup })}</p>}
          </div>
        )}
        {!finished && <p className="text-xs text-muted-foreground">{t("update.confirm.warning_keep_open")}</p>}

        {/* Raw log of the run (tail), collapsed by default */}
        {logTail.length > 0 && (
          <details className="rounded-xl border border-border bg-background/60">
            <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground">
              {t("update.progress.show_log")}
            </summary>
            <pre className="max-h-64 overflow-auto px-3 pb-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all">
              {logTail.join("\n")}
            </pre>
          </details>
        )}

        {retryError && <p className="text-sm text-destructive">{retryError}</p>}

        {finished && (
          <div className="flex flex-wrap justify-end gap-2">
            {state === "failed" ? (
              <>
                <button type="button" className={ghostBtn} onClick={() => setOpen(false)}>
                  {t("update.progress.close")}
                </button>
                <button type="button" className={solidBtn} disabled={retrying} onClick={() => void retry()}>
                  {retrying ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                  )}
                  {t("update.progress.retry")}
                </button>
              </>
            ) : (
              <button type="button" className={outlineBtn} onClick={() => window.location.reload()}>
                {t("update.progress.reload")}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
