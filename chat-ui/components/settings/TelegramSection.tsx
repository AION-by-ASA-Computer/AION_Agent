"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Bot, Check, Copy, ExternalLink, Link2, Loader2, MessageSquare, RefreshCw, Unlink } from "lucide-react";

import {
  TelegramApiError,
  createTelegramLink,
  getTelegramStatus,
  listTelegramBots,
  listTelegramConversations,
  unlinkTelegram,
  type TelegramBot,
  type TelegramBotStatus,
  type TelegramConversation,
  type TelegramPairingLink,
  type TelegramStatus,
} from "@/lib/api/telegram";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { cn } from "@/lib/cn";
import { getLocale } from "@/lib/i18n/i18n-store";
import { useT } from "@/lib/i18n/use-t";
import { Badge, Dialog, Group, Mono, Note, SectionHead, dangerBtn, ghostBtn, outlineBtn, solidBtn } from "./ui";

type TFn = ReturnType<typeof useT>;
type ToastFn = (message: string, type?: "success" | "error") => void;

/** While a pairing link is open, the status is re-read until the bot confirms the link. */
const POLL_MS = 3000;

function errorMessage(err: unknown, t: TFn): string {
  if (err instanceof TelegramApiError) {
    switch (err.code) {
      case "telegram_disabled":
        return t("settings.telegram.disabled");
      case "telegram_unavailable":
        return t("settings.telegram.err.unavailable");
      case "user_token_required":
        return t("settings.telegram.err.user_token_required");
      case "not_linked":
        return t("settings.telegram.err.not_linked");
      default:
        return err.message || t("settings.telegram.err.generic");
    }
  }
  if (err instanceof Error && err.message) return err.message;
  return t("settings.telegram.err.generic");
}

function formatDate(iso: string | null, withTime = false): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const locale = getLocale();
  return withTime
    ? d.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" })
    : d.toLocaleDateString(locale, { dateStyle: "medium" });
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString(getLocale(), { timeStyle: "short" });
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: TelegramStatus };

export function TelegramSection({ onToast }: { onToast?: ToastFn }) {
  const t = useT();
  const userId = useStoredUserId();
  const token = useStoredToken();

  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [pairing, setPairing] = useState<TelegramPairingLink | null>(null);
  const [expired, setExpired] = useState(false);
  const [creating, setCreating] = useState(false);
  const [confirmUnlink, setConfirmUnlink] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const [inlineError, setInlineError] = useState<string | null>(null);

  const notify = useCallback<ToastFn>(
    (message, type = "success") => {
      if (onToast) onToast(message, type);
      else if (type === "error") setInlineError(message);
    },
    [onToast],
  );

  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getTelegramStatus(userId, token)
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

  const refresh = useCallback(() => setReloadKey((k) => k + 1), []);

  // Polling while a link is open: as soon as the bot redeems the code the section flips to "linked".
  useEffect(() => {
    if (!pairing || expired) return;
    const expiresAt = new Date(pairing.expires_at).getTime();
    const id = window.setInterval(async () => {
      if (Date.now() >= expiresAt) {
        setExpired(true);
        return;
      }
      try {
        const data = await getTelegramStatus(userId, token);
        if (data.link) {
          setPairing(null);
          setState({ status: "ready", data });
          notify(t("settings.telegram.toast.linked"));
        }
      } catch {
        /* transient: next tick retries */
      }
    }, POLL_MS);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pairing, expired, userId, token, notify]);

  const generate = async () => {
    setCreating(true);
    setInlineError(null);
    try {
      setPairing(await createTelegramLink(userId, token));
      setExpired(false);
    } catch (err) {
      notify(errorMessage(err, t), "error");
    } finally {
      setCreating(false);
    }
  };

  const handleUnlink = async () => {
    setUnlinking(true);
    try {
      await unlinkTelegram(userId, token);
      setConfirmUnlink(false);
      notify(t("settings.telegram.toast.unlinked"));
      refresh();
    } catch (err) {
      setConfirmUnlink(false);
      notify(errorMessage(err, t), "error");
    } finally {
      setUnlinking(false);
    }
  };

  const head = <SectionHead title={t("settings.telegram.title")} description={t("settings.telegram.desc")} />;

  if (state.status === "loading") {
    return (
      <>
        {head}
        <p className="flex items-center gap-2 py-8 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t("settings.telegram.loading")}
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
                refresh();
              }}
              className={cn(outlineBtn, "text-foreground")}
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              {t("settings.telegram.retry")}
            </button>
          </div>
        </Note>
      </>
    );
  }

  const { data } = state;

  if (!data.enabled) {
    return (
      <>
        {head}
        <Note>{t("settings.telegram.disabled")}</Note>
      </>
    );
  }

  return (
    <>
      {head}
      {inlineError ? <Note tone="error">{inlineError}</Note> : null}

      {data.link ? (
        <Group
          title={t("settings.telegram.linked_title")}
          action={<Badge tone="success">{t("settings.telegram.status.linked")}</Badge>}
          footer={
            <button
              type="button"
              onClick={() => setConfirmUnlink(true)}
              className={cn(ghostBtn, "text-destructive hover:bg-destructive/10 hover:text-destructive")}
            >
              <Unlink className="h-3.5 w-3.5" aria-hidden />
              {t("settings.telegram.unlink")}
            </button>
          }
        >
          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 px-5 py-4 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted-foreground">{t("settings.telegram.account")}</dt>
              <dd className="mt-0.5 font-medium">
                {data.link.tg_username ? `@${data.link.tg_username}` : data.link.tg_first_name || "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("settings.telegram.user_id")}</dt>
              <dd className="mt-0.5">
                <Mono>{data.link.tg_user_id}</Mono>
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("settings.telegram.linked_at")}</dt>
              <dd className="mt-0.5">{formatDate(data.link.linked_at)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("settings.telegram.last_seen")}</dt>
              <dd className="mt-0.5">
                {data.link.last_seen_at ? formatDate(data.link.last_seen_at, true) : t("settings.telegram.never")}
              </dd>
            </div>
          </dl>
          {data.bot_username ? (
            <div className="border-t border-border/60 px-5 py-3">
              <a
                href={`https://t.me/${data.bot_username}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-sm font-medium underline-offset-4 hover:underline"
              >
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                {t("settings.telegram.open_bot", { bot: `@${data.bot_username}` })}
              </a>
            </div>
          ) : null}
        </Group>
      ) : (
        <Group
          title={t("settings.telegram.link_title")}
          description={t("settings.telegram.link_desc")}
          action={<Badge>{t("settings.telegram.status.not_linked")}</Badge>}
        >
          {pairing ? (
            <PairingPanel
              pairing={pairing}
              expired={expired}
              regenerating={creating}
              onRegenerate={() => void generate()}
            />
          ) : (
            <div className="flex flex-col gap-3 px-5 py-4">
              <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
                <li>{t("settings.telegram.step1")}</li>
                <li>{t("settings.telegram.step2", { bot: data.bot_username ? `@${data.bot_username}` : "AION" })}</li>
                <li>{t("settings.telegram.step3")}</li>
              </ol>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => void generate()}
                  disabled={creating || !data.available}
                  className={solidBtn}
                >
                  {creating ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  ) : (
                    <Link2 className="h-3.5 w-3.5" aria-hidden />
                  )}
                  {t("settings.telegram.link_button")}
                </button>
                {!data.available ? (
                  <span className="text-xs text-muted-foreground">{t("settings.telegram.err.unavailable")}</span>
                ) : null}
              </div>
            </div>
          )}
        </Group>
      )}

      {data.link ? <TelegramBots userId={userId} token={token} managerBot={data.bot_username} /> : null}

      <TelegramChats userId={userId} token={token} />

      {confirmUnlink ? (
        <Dialog
          title={t("settings.telegram.unlink_dialog.title")}
          description={t("settings.telegram.unlink_dialog.desc")}
          closeLabel={t("settings.telegram.cancel")}
          onClose={() => {
            if (!unlinking) setConfirmUnlink(false);
          }}
        >
          <div className="flex justify-end gap-2 pt-4">
            <button
              type="button"
              onClick={() => setConfirmUnlink(false)}
              disabled={unlinking}
              className={ghostBtn}
              autoFocus
            >
              {t("settings.telegram.cancel")}
            </button>
            <button type="button" onClick={() => void handleUnlink()} disabled={unlinking} className={dangerBtn}>
              {unlinking ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : (
                <Unlink className="h-3.5 w-3.5" aria-hidden />
              )}
              {t("settings.telegram.unlink_dialog.confirm")}
            </button>
          </div>
        </Dialog>
      ) : null}
    </>
  );
}

function PairingPanel({
  pairing,
  expired,
  regenerating,
  onRegenerate,
}: {
  pairing: TelegramPairingLink;
  expired: boolean;
  regenerating: boolean;
  onRegenerate: () => void;
}) {
  const t = useT();
  const [copied, setCopied] = useState(false);

  if (expired) {
    return (
      <div className="flex flex-col items-start gap-3 px-5 py-4">
        <Note tone="warn">{t("settings.telegram.expired")}</Note>
        <button type="button" onClick={onRegenerate} disabled={regenerating} className={solidBtn}>
          {regenerating ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          )}
          {t("settings.telegram.regenerate")}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5 px-5 py-4 sm:flex-row sm:items-center">
      {pairing.qr_svg ? (
        // eslint-disable-next-line @next/next/no-img-element -- data URI SVG generated by the backend
        <img
          src={pairing.qr_svg}
          alt={t("settings.telegram.qr_alt")}
          width={176}
          height={176}
          className="h-44 w-44 shrink-0 self-center rounded-xl bg-white p-2"
        />
      ) : null}
      <div className="flex min-w-0 flex-col gap-3">
        <p className="text-sm text-muted-foreground">{t("settings.telegram.pairing_hint")}</p>
        <div className="flex flex-wrap gap-2">
          <a href={pairing.url} target="_blank" rel="noopener noreferrer" className={solidBtn}>
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            {t("settings.telegram.open_telegram")}
          </a>
          <button
            type="button"
            onClick={async () => {
              const ok = await copyText(pairing.url);
              setCopied(ok);
              if (ok) window.setTimeout(() => setCopied(false), 2000);
            }}
            className={outlineBtn}
          >
            {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
            {copied ? t("settings.telegram.copied") : t("settings.telegram.copy_link")}
          </button>
        </div>
        <p className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          {t("settings.telegram.waiting", { time: formatTime(pairing.expires_at) })}
        </p>
      </div>
    </div>
  );
}

type BotsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: TelegramBot[] };

const BOT_STATUS_TONE: Record<TelegramBotStatus, "neutral" | "success" | "warning" | "danger"> = {
  provisioning: "neutral",
  active: "success",
  suspended: "warning",
  error: "danger",
};

/** Personal assistants: created and managed on Telegram (/newbot, /mybots), listed here with a direct link. */
function TelegramBots({
  userId,
  token,
  managerBot,
}: {
  userId: string;
  token: string | null;
  managerBot: string | null;
}) {
  const t = useT();
  const [state, setState] = useState<BotsState>({ status: "loading" });
  const manager = managerBot ? `@${managerBot}` : "AION";

  useEffect(() => {
    let cancelled = false;
    listTelegramBots(userId, token)
      .then((items) => {
        if (!cancelled) setState({ status: "ready", items });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ status: "error", message: errorMessage(err, t) });
      });
    return () => {
      cancelled = true;
    };
    // `t` is a stable module-level function.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, token]);

  return (
    <Group title={t("settings.telegram.bots_title")} description={t("settings.telegram.bots_desc", { bot: manager })}>
      {state.status === "loading" ? (
        <p className="flex items-center justify-center gap-2 px-5 py-8 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t("settings.telegram.loading")}
        </p>
      ) : state.status === "error" ? (
        <div className="px-5 py-4">
          <Note tone="error">{state.message}</Note>
        </div>
      ) : state.items.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-muted-foreground">
          {t("settings.telegram.bots_empty", { bot: manager })}
        </p>
      ) : (
        <ul className="divide-y divide-border/40">
          {state.items.map((b) => (
            <li key={b.id} className="flex items-center gap-3 px-5 py-3">
              <Bot className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-medium">{b.name || b.username}</span>
                  {b.username ? <Mono>@{b.username}</Mono> : null}
                  <Badge tone={BOT_STATUS_TONE[b.status] ?? "neutral"}>
                    {t(`settings.telegram.bot_status_${b.status}`)}
                  </Badge>
                  <Badge>{t(`settings.telegram.bot_mode_${b.mode === "shared" ? "shared" : "personal"}`)}</Badge>
                </span>
                <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                  {[
                    b.profile_name ? t("settings.telegram.bot_profile", { profile: b.profile_name }) : null,
                    b.project_slug ? t("settings.telegram.bot_project", { project: b.project_slug }) : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </span>
              {b.url ? (
                <a href={b.url} target="_blank" rel="noopener noreferrer" className={outlineBtn}>
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                  {t("settings.telegram.bot_open")}
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Group>
  );
}

type ChatsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: TelegramConversation[] };

/** Chats started from Telegram: hidden from the sidebar, opened read-only. */
function TelegramChats({ userId, token }: { userId: string; token: string | null }) {
  const t = useT();
  const [state, setState] = useState<ChatsState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    listTelegramConversations(userId, token)
      .then((items) => {
        if (!cancelled) setState({ status: "ready", items });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ status: "error", message: errorMessage(err, t) });
      });
    return () => {
      cancelled = true;
    };
    // `t` is a stable module-level function.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, token]);

  return (
    <Group title={t("settings.telegram.chats_title")} description={t("settings.telegram.chats_desc")}>
      {state.status === "loading" ? (
        <p className="flex items-center justify-center gap-2 px-5 py-8 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t("settings.telegram.loading")}
        </p>
      ) : state.status === "error" ? (
        <div className="px-5 py-4">
          <Note tone="error">{state.message}</Note>
        </div>
      ) : state.items.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-muted-foreground">{t("settings.telegram.chats_empty")}</p>
      ) : (
        <ul className="divide-y divide-border/40">
          {state.items.map((c) => (
            <li key={c.id}>
              <Link
                href={`/c/${c.id}`}
                className="focus-ring flex items-center gap-3 px-5 py-3 transition-colors hover:bg-secondary/50"
              >
                <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {c.title || c.preview || t("settings.telegram.chat_untitled")}
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {c.telegram_bot ? `@${c.telegram_bot}` : t("settings.telegram.chat_via_manager")}
                    {c.telegram_chat ? ` · ${t("settings.telegram.chat_in_group", { chat: c.telegram_chat })}` : null}
                    {" · "}
                    {t("settings.telegram.chat_meta", {
                      count: c.message_count,
                      date: formatDate(c.updated_at || c.created_at, true),
                    })}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Group>
  );
}
