"use client";

/**
 * "Assistants" section of the admin Telegram page: every bot created from the manager
 * bot, with owner, profile/project, state and the admin actions (suspend, resume,
 * reassign after an ownership transfer, delete). Backed by `/admin/telegram/bots*`.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Pause, Play, RefreshCw, Trash2, UserCheck } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { fullWhen, shortWhen, toMs } from "@/lib/datetime";
import { DeleteDialog } from "@/components/ui/ConfirmDialogs";
import { SearchField } from "@/components/ui/SearchField";
import { ghostBtn, outlineBtn } from "@/components/ui/classes";
import { EmptyList, Loading, k, readJson, userLabel, type Notify, type T, type UserRef } from "./shared";

type AdminBot = {
  id: number;
  bot_tg_id: number;
  username: string | null;
  name: string | null;
  mode: "personal" | "shared";
  status: "provisioning" | "active" | "suspended" | "error" | "deleted";
  last_error: string | null;
  profile_slug: string | null;
  project_slug: string | null;
  owner: UserRef;
  pending_owner: { tg_user_id: number; linked_user: UserRef | null } | null;
  running: boolean;
  created_at: string | null;
  last_activity_at: string | null;
};

type BotAction = "suspend" | "resume" | "reassign" | "delete";

// State colours only where they carry meaning: active / suspended / error.
const STATUS_TONE: Record<AdminBot["status"], string> = {
  active: "bg-success/12 text-success",
  suspended: "bg-warning/15 text-warning",
  error: "bg-destructive/12 text-destructive",
  provisioning: "bg-secondary text-muted-foreground",
  deleted: "bg-secondary text-muted-foreground",
};

/**
 * @param rev bumped by the page after the Telegram config is saved, so the list
 *            reloads (the gateway restarts and `running` may change).
 */
export function TelegramBotsList({ t, notify, rev }: { t: T; notify: Notify; rev: number }) {
  const [bots, setBots] = useState<AdminBot[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState("");
  const [showDeleted, setShowDeleted] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<AdminBot | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await readJson<{ data: AdminBot[] }>(
        await apiFetch(`${apiBase()}/admin/telegram/bots?include_deleted=${showDeleted}`),
      );
      setBots(data.data);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [showDeleted]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount / filter change / config save
    void load();
  }, [load, rev]);

  /** Run an admin action on one bot, then reload; backend error codes map to `err.*`. */
  const act = async (bot: AdminBot, action: BotAction) => {
    setBusy(bot.id);
    try {
      const res = await readJson<{ revoked?: boolean }>(
        await apiFetch(`${apiBase()}/admin/telegram/bots/${bot.id}/${action}`, { method: "POST" }),
      );
      // Delete with the gateway off removes the bot in AION but cannot revoke its token on Telegram.
      if (action === "delete" && res.revoked === false) notify(t(`${k}.done.delete_not_revoked`), "warning");
      else notify(t(`${k}.done.${action}`), "success");
      setDeleting(null);
      await load();
    } catch (e) {
      const code = e instanceof Error ? e.message : "";
      notify(t(`${k}.err.${code}`) !== `${k}.err.${code}` ? t(`${k}.err.${code}`) : t(`${k}.err.generic`), "error");
    } finally {
      setBusy(null);
    }
  };

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!bots) return [];
    if (!q) return bots;
    return bots.filter((b) =>
      [b.username, b.name, b.owner.identifier, b.owner.display_name, b.profile_slug, b.project_slug]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q)),
    );
  }, [bots, query]);

  if (failed) {
    return (
      <div className="flex flex-col items-start gap-3 py-6">
        <p className="text-sm text-muted-foreground">{t(`${k}.load_failed`)}</p>
        <button type="button" className={outlineBtn} onClick={() => void load()}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          {t(`${k}.retry`)}
        </button>
      </div>
    );
  }
  if (!bots) return <Loading t={t} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-[14rem] flex-1">
          <SearchField value={query} onChange={setQuery} placeholder={t(`${k}.search`)} />
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)} />
          {t(`${k}.show_deleted`)}
        </label>
        <button type="button" className={ghostBtn} onClick={() => void load()}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          {t(`${k}.refresh`)}
        </button>
      </div>

      {visible.length === 0 ? (
        <EmptyList>{bots.length === 0 ? t(`${k}.empty`) : t(`${k}.no_match`)}</EmptyList>
      ) : (
        <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border bg-card/60">
          {visible.map((b) => (
            <li key={b.id} className="flex flex-col gap-3 px-5 py-4 md:flex-row md:items-center">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-medium">{b.name || b.username || b.bot_tg_id}</span>
                  {b.username && <span className="font-mono text-xs text-muted-foreground">@{b.username}</span>}
                  <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", STATUS_TONE[b.status])}>
                    {t(`${k}.status.${b.status}`)}
                  </span>
                  <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground">
                    {t(`${k}.mode.${b.mode}`)}
                  </span>
                  {b.running && (
                    <span className="flex items-center gap-1.5 text-xs text-success">
                      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-success" />
                      {t(`${k}.listening`)}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t(`${k}.owner`, { owner: userLabel(b.owner) })}
                  {b.owner.tg_username ? ` (@${b.owner.tg_username})` : ""}
                  {" · "}
                  {t(`${k}.profile`, { profile: b.profile_slug || "—" })}
                  {" · "}
                  {t(`${k}.project`, { project: b.project_slug || t(`${k}.none`) })}
                  {" · "}
                  {b.last_activity_at
                    ? t(`${k}.last_activity`, { when: shortWhen(toMs(b.last_activity_at)) })
                    : t(`${k}.never_used`)}
                </p>
                {b.pending_owner && (
                  <p className="mt-1 text-xs text-warning">
                    {b.pending_owner.linked_user
                      ? t(`${k}.pending_owner`, { owner: userLabel(b.pending_owner.linked_user) })
                      : t(`${k}.pending_owner_unlinked`, { id: b.pending_owner.tg_user_id })}
                  </p>
                )}
                {b.last_error && !b.pending_owner && (
                  <p className="mt-1 text-xs text-muted-foreground" title={fullWhen(toMs(b.created_at))}>
                    {t(`${k}.last_error`, { error: b.last_error })}
                  </p>
                )}
              </div>
              {b.status !== "deleted" && (
                <div className="flex flex-wrap gap-2">
                  {/* Reassign only confirms a transfer done on Telegram, and needs the new owner linked to AION. */}
                  {b.pending_owner && (
                    <button
                      type="button"
                      className={outlineBtn}
                      disabled={busy === b.id || !b.pending_owner.linked_user}
                      onClick={() => void act(b, "reassign")}
                    >
                      <UserCheck className="h-3.5 w-3.5" aria-hidden />
                      {t(`${k}.action.reassign`)}
                    </button>
                  )}
                  {b.status === "active" ? (
                    <button type="button" className={outlineBtn} disabled={busy === b.id} onClick={() => void act(b, "suspend")}>
                      <Pause className="h-3.5 w-3.5" aria-hidden />
                      {t(`${k}.action.suspend`)}
                    </button>
                  ) : (
                    !b.pending_owner && (
                      <button type="button" className={outlineBtn} disabled={busy === b.id} onClick={() => void act(b, "resume")}>
                        <Play className="h-3.5 w-3.5" aria-hidden />
                        {t(`${k}.action.resume`)}
                      </button>
                    )
                  )}
                  <button
                    type="button"
                    className={cn(ghostBtn, "text-destructive hover:bg-destructive/10 hover:text-destructive")}
                    disabled={busy === b.id}
                    onClick={() => setDeleting(b)}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden />
                    {t(`${k}.action.delete`)}
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {deleting && (
        <DeleteDialog
          name={deleting.username || String(deleting.bot_tg_id)}
          busy={busy === deleting.id}
          ns={`${k}.delete`}
          t={t}
          onConfirm={() => void act(deleting, "delete")}
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
