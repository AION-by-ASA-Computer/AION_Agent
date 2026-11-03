"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw } from "lucide-react";
import { apiBase } from "@/lib/api";
import { outlineBtn, solidBtn } from "@/components/ui/classes";
import { useT } from "@/lib/i18n/use-t";

interface RestartOverlayProps {
  isOpen: boolean;
  onSuccess: () => void;
  onDismiss?: () => void;
  title?: string;
  initialHint?: string;
  maxSeconds?: number;
}

export function RestartOverlay({
  isOpen,
  onSuccess,
  onDismiss,
  title,
  initialHint,
  maxSeconds = 180,
}: RestartOverlayProps) {
  const t = useT();
  const [elapsed, setElapsed] = useState(0);
  const [timedOut, setTimedOut] = useState(false);
  const [probing, setProbing] = useState(false);
  const [success, setSuccess] = useState(false);
  const [limit, setLimit] = useState(maxSeconds);
  const successCalledRef = useRef(false);

  const checkHealth = useCallback(async (): Promise<boolean> => {
    try {
      const res = await fetch(`${apiBase()}/health`, {
        cache: "no-store",
        headers: { "Cache-Control": "no-cache" },
      });
      if (res.ok) {
        const data = await res.json().catch(() => null);
        if (data && data.status === "ok") {
          return true;
        }
      }
    } catch {
      // Backend not yet ready (connection refused, 502 Bad Gateway from reverse proxy, etc.)
    }
    return false;
  }, []);

  const handleManualProbe = useCallback(async () => {
    setProbing(true);
    const ok = await checkHealth();
    setProbing(false);
    if (ok && !successCalledRef.current) {
      successCalledRef.current = true;
      setSuccess(true);
      setTimeout(() => {
        onSuccess();
      }, 500);
    }
  }, [checkHealth, onSuccess]);

  useEffect(() => {
    if (!isOpen) {
      setElapsed(0);
      setTimedOut(false);
      setSuccess(false);
      setLimit(maxSeconds);
      successCalledRef.current = false;
      return;
    }

    let active = true;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let tickTimer: ReturnType<typeof setInterval> | null = null;

    // Tick elapsed time each second
    tickTimer = setInterval(() => {
      setElapsed((prev) => {
        const next = prev + 1;
        if (next >= limit) {
          setTimedOut(true);
        }
        return next;
      });
    }, 1000);

    // Initial grace delay of 2.5s to let the exiting container terminate cleanly
    const startDelay = setTimeout(() => {
      if (!active) return;

      const runPoll = async () => {
        if (!active || successCalledRef.current) return;
        const ok = await checkHealth();
        if (ok && active && !successCalledRef.current) {
          successCalledRef.current = true;
          if (pollTimer) clearInterval(pollTimer);
          if (tickTimer) clearInterval(tickTimer);
          setSuccess(true);
          setTimeout(() => {
            if (active) onSuccess();
          }, 600);
        }
      };

      // Run initial probe then interval
      void runPoll();
      pollTimer = setInterval(() => {
        void runPoll();
      }, 2000);
    }, 2500);

    return () => {
      active = false;
      clearTimeout(startDelay);
      if (pollTimer) clearInterval(pollTimer);
      if (tickTimer) clearInterval(tickTimer);
    };
  }, [isOpen, limit, maxSeconds, checkHealth, onSuccess]);

  if (!isOpen) return null;

  const handleContinueWaiting = () => {
    setLimit((prev) => prev + 90);
    setTimedOut(false);
    void handleManualProbe();
  };

  const getHint = () => {
    if (initialHint && elapsed < 20) return initialHint;
    if (elapsed < 20) {
      return (
        t("restart_overlay.hint_initial") ||
        "Applicazione della nuova configurazione e riavvio dei servizi..."
      );
    }
    return (
      t("restart_overlay.hint_slow") ||
      "Riavvio dei servizi e inizializzazione dei tool MCP in corso... Attendere..."
    );
  };

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="restart-overlay-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4 animate-in fade-in duration-200"
    >
      <div className="flex w-full max-w-md flex-col items-center gap-4 rounded-3xl border border-border bg-card p-6 text-center shadow-2xl">
        {success ? (
          <>
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-500/10 text-emerald-500">
              <CheckCircle2 className="h-6 w-6" aria-hidden />
            </div>
            <div>
              <h2
                id="restart-overlay-title"
                className="text-lg font-semibold tracking-[-0.015em]"
              >
                {t("restart_overlay.success_title") ||
                  "API riavviata con successo"}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("restart_overlay.success_body") ||
                  "La nuova configurazione è attiva. Aggiornamento in corso..."}
              </p>
            </div>
          </>
        ) : timedOut ? (
          <>
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-500/10 text-amber-500">
              <AlertTriangle className="h-6 w-6" aria-hidden />
            </div>
            <div>
              <h2
                id="restart-overlay-title"
                className="text-lg font-semibold tracking-[-0.015em]"
              >
                {t("restart_overlay.timed_out_title") ||
                  "Il server non risponde ancora"}
              </h2>
              <p className="mt-1.5 text-sm text-muted-foreground">
                {t("restart_overlay.timed_out_body") ||
                  `Il riavvio ha impiegato più di ${Math.round(elapsed)}s. Il container potrebbe essere ancora in fase di caricamento o potrebbe essersi verificato un errore.`}
              </p>
            </div>
            <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
              <button
                type="button"
                className={outlineBtn}
                onClick={handleContinueWaiting}
              >
                {t("restart_overlay.continue_waiting") ||
                  "Continua ad attendere (+90s)"}
              </button>
              <button
                type="button"
                className={solidBtn}
                onClick={() => void handleManualProbe()}
                disabled={probing}
              >
                {probing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                )}
                {t("restart_overlay.retry_now") || "Verifica adesso"}
              </button>
              <button
                type="button"
                className={outlineBtn}
                onClick={() => window.location.reload()}
              >
                {t("restart_overlay.reload_page") || "Ricarica pagina"}
              </button>
              {onDismiss && (
                <button
                  type="button"
                  className="mt-1 block w-full text-xs text-muted-foreground hover:underline"
                  onClick={onDismiss}
                >
                  {t("restart_overlay.dismiss") || "Chiudi finestra"}
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <Loader2 className="h-6 w-6 animate-spin text-primary" aria-hidden />
            </div>
            <div>
              <h2
                id="restart-overlay-title"
                className="text-lg font-semibold tracking-[-0.015em]"
              >
                {title ||
                  t("restart_overlay.title") ||
                  "Riavvio dell'API in corso"}
              </h2>
              <p className="mt-1.5 text-sm text-muted-foreground">
                {getHint()}
              </p>
            </div>
            <div className="rounded-full bg-secondary/80 px-3 py-1 font-mono text-xs text-muted-foreground">
              {elapsed}s
            </div>
          </>
        )}
      </div>
    </div>
  );
}
