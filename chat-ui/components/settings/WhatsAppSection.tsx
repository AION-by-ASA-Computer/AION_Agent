"use client";

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, Loader2, MessageCircle, RefreshCw, Unlink } from "lucide-react";

import {
  WhatsAppError,
  createWhatsAppLinkCode,
  getWhatsAppStatus,
  unlinkWhatsApp,
  type WhatsAppLinkCode,
  type WhatsAppStatus,
} from "@/lib/api/whatsapp";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { cn } from "@/lib/cn";
import { getLocale } from "@/lib/i18n/i18n-store";
import { useT } from "@/lib/i18n/use-t";
import { Badge, Dialog, Group, Mono, Note, SectionHead, dangerBtn, ghostBtn, outlineBtn, solidBtn } from "./ui";

type TFn = ReturnType<typeof useT>;
type ToastFn = (message: string, type?: "success" | "error") => void;

const POLL_MS = 3000;

function errorMessage(err: unknown, t: TFn): string {
  if (err instanceof WhatsAppError) {
    if (err.code === "whatsapp_channel_disabled") return t("settings.whatsapp.err.disabled");
    return err.message || t("settings.whatsapp.err.generic");
  }
  if (err instanceof Error && err.message) return err.message;
  return t("settings.whatsapp.err.generic");
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(getLocale(), { dateStyle: "medium", timeStyle: "short" });
}

function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: WhatsAppStatus };

export function WhatsAppSection({ onToast }: { onToast?: ToastFn }) {
  const t = useT();
  const userId = useStoredUserId();
  const token = useStoredToken();

  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const [linkCode, setLinkCode] = useState<WhatsAppLinkCode | null>(null);
  const [now, setNow] = useState(0);
  const [generating, setGenerating] = useState(false);
  const [unlinkOpen, setUnlinkOpen] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const [inlineError, setInlineError] = useState<string | null>(null);

  const notify = useCallback<ToastFn>(
    (message, type = "success") => {
      if (onToast) onToast(message, type);
      else if (type === "error") setInlineError(message);
    },
    [onToast],
  );

  useEffect(() => {
    let cancelled = false;
    getWhatsAppStatus(userId, token)
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ status: "error", message: errorMessage(err, t) });
      });
    return () => {
      cancelled = true;
    };
    // `t` is a stable module-level function; reloadKey triggers refreshes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, token, reloadKey]);

  const expiresAt = linkCode ? Date.parse(linkCode.expires_at) : 0;
  const remaining = linkCode ? Math.max(0, Math.ceil((expiresAt - now) / 1000)) : 0;
  const codeActive = linkCode !== null && remaining > 0;

  // Countdown tick while a code is on screen.
  useEffect(() => {
    if (!codeActive) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [codeActive]);

  // Poll the link status until the user sends the code from WhatsApp.
  useEffect(() => {
    if (!codeActive) return;
    let cancelled = false;
    const id = window.setInterval(() => {
      getWhatsAppStatus(userId, token)
        .then((data) => {
          if (cancelled || !data.linked) return;
          setLinkCode(null);
          setState({ status: "ready", data });
          notify(t("settings.whatsapp.toast.linked"));
        })
        .catch(() => {
          /* transient: the next tick retries */
        });
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [codeActive, userId, token, notify]);

  const generate = async () => {
    setGenerating(true);
    setInlineError(null);
    try {
      const code = await createWhatsAppLinkCode(userId, token);
      setNow(Date.now());
      setLinkCode(code);
    } catch (err) {
      notify(errorMessage(err, t), "error");
    } finally {
      setGenerating(false);
    }
  };

  const handleUnlink = async () => {
    setUnlinking(true);
    try {
      await unlinkWhatsApp(userId, token);
      setUnlinkOpen(false);
      setInlineError(null);
      notify(t("settings.whatsapp.toast.unlinked"));
      setReloadKey((k) => k + 1);
    } catch (err) {
      setUnlinkOpen(false);
      notify(errorMessage(err, t), "error");
    } finally {
      setUnlinking(false);
    }
  };

  const head = <SectionHead title={t("settings.whatsapp.title")} description={t("settings.whatsapp.desc")} />;

  if (state.status === "loading") {
    return (
      <>
        {head}
        <p className="flex items-center gap-2 py-8 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t("settings.whatsapp.loading")}
        </p>
      </>
    );
  }

  if (state.status === "error") {
    return (
      <>
        {head}
        <Note tone="error">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>{state.message}</span>
            <button
              type="button"
              onClick={() => {
                setState({ status: "loading" });
                setReloadKey((k) => k + 1);
              }}
              className={cn(outlineBtn, "text-foreground")}
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              {t("settings.whatsapp.retry")}
            </button>
          </div>
        </Note>
      </>
    );
  }

  const status = state.data;

  if (!status.channel_enabled) {
    return (
      <>
        {head}
        <Note>{t("settings.whatsapp.disabled")}</Note>
      </>
    );
  }

  if (status.linked) {
    return (
      <>
        {head}
        {inlineError ? <Note tone="error">{inlineError}</Note> : null}
        <Group
          title={t("settings.whatsapp.linked_title")}
          action={<Badge tone="success">{t("settings.whatsapp.linked_badge")}</Badge>}
          footer={
            <button
              type="button"
              onClick={() => setUnlinkOpen(true)}
              className={cn(ghostBtn, "text-destructive hover:bg-destructive/10 hover:text-destructive")}
            >
              <Unlink className="h-3.5 w-3.5" aria-hidden />
              {t("settings.whatsapp.unlink")}
            </button>
          }
        >
          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 px-5 py-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs text-muted-foreground">{t("settings.whatsapp.profile_name")}</dt>
              <dd className="mt-0.5 truncate">{status.wa_profile_name || "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("settings.whatsapp.phone")}</dt>
              <dd className="mt-0.5">{status.phone_hint ? <Mono>{status.phone_hint}</Mono> : "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("settings.whatsapp.linked_at")}</dt>
              <dd className="mt-0.5">{formatDateTime(status.linked_at) || "—"}</dd>
            </div>
          </dl>
        </Group>
        <Note>{t("settings.whatsapp.linked_hint")}</Note>

        {unlinkOpen ? (
          <Dialog
            title={t("settings.whatsapp.unlink_dialog.title")}
            description={t("settings.whatsapp.unlink_dialog.desc")}
            closeLabel={t("settings.whatsapp.unlink_dialog.cancel")}
            onClose={() => {
              if (!unlinking) setUnlinkOpen(false);
            }}
          >
            <div className="flex justify-end gap-2 pt-4">
              <button
                type="button"
                onClick={() => setUnlinkOpen(false)}
                disabled={unlinking}
                className={ghostBtn}
                autoFocus
              >
                {t("settings.whatsapp.unlink_dialog.cancel")}
              </button>
              <button type="button" onClick={() => void handleUnlink()} disabled={unlinking} className={dangerBtn}>
                {unlinking ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <Unlink className="h-3.5 w-3.5" aria-hidden />
                )}
                {unlinking ? t("settings.whatsapp.unlink_dialog.unlinking") : t("settings.whatsapp.unlink_dialog.confirm")}
              </button>
            </div>
          </Dialog>
        ) : null}
      </>
    );
  }

  const steps = [
    t("settings.whatsapp.step_scan"),
    t("settings.whatsapp.step_send"),
    t("settings.whatsapp.step_done"),
  ];

  return (
    <>
      {head}
      {inlineError ? <Note tone="error">{inlineError}</Note> : null}

      <Group
        title={t("settings.whatsapp.link_title")}
        description={
          status.display_phone_number
            ? t("settings.whatsapp.link_desc_number", { number: status.display_phone_number })
            : t("settings.whatsapp.link_desc")
        }
      >
        <div className="flex flex-col gap-5 px-5 py-5">
          <ol className="flex flex-col gap-2 text-sm">
            {steps.map((step, i) => (
              <li key={i} className="flex items-start gap-2.5">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold tabular-nums">
                  {i + 1}
                </span>
                <span className="text-muted-foreground">{step}</span>
              </li>
            ))}
          </ol>

          {linkCode ? (
            codeActive ? (
              <div className="flex flex-col items-center gap-4 rounded-2xl border border-border bg-background px-4 py-5 sm:flex-row sm:items-center sm:gap-6 sm:px-6">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={linkCode.qr_svg}
                  alt={t("settings.whatsapp.qr_alt")}
                  width={176}
                  height={176}
                  className="shrink-0 rounded-xl border border-border/70 bg-white p-2 shadow-sm"
                />
                <div className="flex min-w-0 flex-1 flex-col items-center gap-3 sm:items-start">
                  <div className="text-center sm:text-left">
                    <p className="text-xs text-muted-foreground">{t("settings.whatsapp.code_label")}</p>
                    <p className="mt-1 select-all font-mono text-3xl font-semibold tracking-[0.2em]">{linkCode.code}</p>
                  </div>
                  <a href={linkCode.wa_link} target="_blank" rel="noopener noreferrer" className={solidBtn}>
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                    {t("settings.whatsapp.open")}
                  </a>
                  <p className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    <span>
                      {t("settings.whatsapp.waiting")}{" "}
                      <span className="tabular-nums">
                        {t("settings.whatsapp.expires_in", { time: formatCountdown(remaining) })}
                      </span>
                    </span>
                  </p>
                  <button type="button" onClick={() => void generate()} disabled={generating} className={ghostBtn}>
                    <RefreshCw className={cn("h-3.5 w-3.5", generating && "animate-spin")} aria-hidden />
                    {t("settings.whatsapp.regenerate")}
                  </button>
                </div>
              </div>
            ) : (
              <Note tone="warn">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span>{t("settings.whatsapp.expired")}</span>
                  <button
                    type="button"
                    onClick={() => void generate()}
                    disabled={generating}
                    className={cn(outlineBtn, "text-foreground")}
                  >
                    <RefreshCw className={cn("h-3.5 w-3.5", generating && "animate-spin")} aria-hidden />
                    {t("settings.whatsapp.regenerate")}
                  </button>
                </div>
              </Note>
            )
          ) : (
            <div>
              <button type="button" onClick={() => void generate()} disabled={generating} className={solidBtn}>
                {generating ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <MessageCircle className="h-3.5 w-3.5" aria-hidden />
                )}
                {t("settings.whatsapp.link")}
              </button>
            </div>
          )}
        </div>
      </Group>
    </>
  );
}
