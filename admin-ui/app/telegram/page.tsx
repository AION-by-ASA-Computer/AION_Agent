"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Loader2, Pause, Play, RefreshCw, Settings, Trash2, UserCheck } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { PageToast, type ToastState } from "@/components/PageToast";
import { DeleteDialog } from "@/components/ui/ConfirmDialogs";
import { SearchField } from "@/components/ui/SearchField";
import { ghostBtn, inputCls, outlineBtn } from "@/components/ui/classes";
import { fullWhen, shortWhen, toMs } from "@/lib/datetime";

const k = "admin_telegram";

type UserRef = { row_id: string; identifier?: string; display_name?: string | null; tg_username?: string | null };

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

type QuotaRow = UserRef & { linked: boolean; bots: number; max_bots: number | null };

type AuditRow = {
  id: number;
  ts: string | null;
  action: string;
  user: UserRef | null;
  actor_tg_user_id: number | null;
  payload: Record<string, unknown>;
};

type Tab = "bots" | "quotas" | "audit";
type BotAction = "suspend" | "resume" | "reassign" | "delete";

const STATUS_TONE: Record<AdminBot["status"], string> = {
  active: "bg-success/12 text-success",
  suspended: "bg-warning/15 text-warning",
  error: "bg-destructive/12 text-destructive",
  provisioning: "bg-secondary text-muted-foreground",
  deleted: "bg-secondary text-muted-foreground",
};

const userLabel = (u?: UserRef | null) => (u ? u.display_name || u.identifier || u.row_id : "—");

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = (body as { detail?: { code?: string } | string }).detail;
    throw new Error(typeof detail === "string" ? detail : detail?.code || String(res.status));
  }
  return res.json() as Promise<T>;
}

export default function TelegramAdminPage() {
  const t = useT();
  const [tab, setTab] = useState<Tab>("bots");
  const [toast, setToast] = useState<ToastState>(null);

  return (
    <div className="mx-auto max-w-6xl pb-16">
      <header className="flex flex-wrap items-end gap-4 pb-6">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-3xl">{t(`${k}.title`)}</h1>
          <p className="mt-1 max-w-[62ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
        </div>
        <Link href="/settings#telegram" className={outlineBtn}>
          <Settings className="h-3.5 w-3.5" aria-hidden />
          {t(`${k}.settings_link`)}
        </Link>
      </header>

      <div role="tablist" aria-label={t(`${k}.tabs_aria`)} className="mb-5 flex gap-1 border-b border-border">
        {(["bots", "quotas", "audit"] as Tab[]).map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn(
              "focus-ring -mb-px border-b-2 px-3 py-2 text-sm transition-colors",
              tab === id ? "border-foreground font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t(`${k}.tab.${id}`)}
          </button>
        ))}
      </div>

      {tab === "bots" && <BotsTab t={t} notify={(message, variant = "info") => setToast({ message, variant })} />}
      {tab === "quotas" && <QuotasTab t={t} notify={(message, variant = "info") => setToast({ message, variant })} />}
      {tab === "audit" && <AuditTab t={t} />}

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}

type T = ReturnType<typeof useT>;
type Notify = (message: string, variant?: "success" | "error" | "warning" | "info") => void;

function Loading({ t }: { t: T }) {
  return (
    <p className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground" role="status">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {t(`${k}.loading`)}
    </p>
  );
}

// ---------- assistenti ----------
function BotsTab({ t, notify }: { t: T; notify: Notify }) {
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
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount / filter change
    void load();
  }, [load]);

  const act = async (bot: AdminBot, action: BotAction) => {
    setBusy(bot.id);
    try {
      const res = await readJson<{ revoked?: boolean }>(
        await apiFetch(`${apiBase()}/admin/telegram/bots/${bot.id}/${action}`, { method: "POST" }),
      );
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
      <div className="flex flex-col items-start gap-3 py-10">
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
    <section className="flex flex-col gap-4">
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
        <p className="rounded-2xl border border-dashed border-border px-5 py-12 text-center text-sm text-muted-foreground">
          {bots.length === 0 ? t(`${k}.empty`) : t(`${k}.no_match`)}
        </p>
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
                  {b.running && <span className="text-xs text-success">● {t(`${k}.listening`)}</span>}
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
    </section>
  );
}

// ---------- quote ----------
function QuotasTab({ t, notify }: { t: T; notify: Notify }) {
  const [rows, setRows] = useState<QuotaRow[] | null>(null);
  const [def, setDef] = useState(0);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await readJson<{ default: number; data: QuotaRow[] }>(
        await apiFetch(`${apiBase()}/admin/telegram/quotas`),
      );
      setRows(data.data);
      setDef(data.default);
      setDrafts({});
    } catch {
      setRows([]);
      notify(t(`${k}.load_failed`), "error");
    }
  }, [notify, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async (row: QuotaRow, value: number | null) => {
    setBusy(row.row_id);
    try {
      await readJson(
        await apiFetch(`${apiBase()}/admin/telegram/quotas/${encodeURIComponent(row.row_id)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ max_bots: value }),
        }),
      );
      notify(t(`${k}.quota_saved`), "success");
      await load();
    } catch {
      notify(t(`${k}.quota_invalid`), "error");
    } finally {
      setBusy(null);
    }
  };

  if (!rows) return <Loading t={t} />;
  return (
    <section className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">{t(`${k}.quota_hint`, { n: def })}</p>
      {rows.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-border px-5 py-12 text-center text-sm text-muted-foreground">
          {t(`${k}.quota_empty`)}
        </p>
      ) : (
        <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border bg-card/60">
          {rows.map((r) => {
            const draft = drafts[r.row_id] ?? (r.max_bots == null ? "" : String(r.max_bots));
            const parsed = draft.trim() === "" ? null : Number(draft);
            const valid = parsed === null || (Number.isInteger(parsed) && parsed >= 0 && parsed <= 100);
            const changed = (parsed ?? null) !== (r.max_bots ?? null);
            return (
              <li key={r.row_id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{userLabel(r)}</p>
                  <p className="text-xs text-muted-foreground">
                    {r.linked ? (r.tg_username ? `@${r.tg_username}` : t(`${k}.linked`)) : t(`${k}.not_linked`)}
                    {" · "}
                    {t(`${k}.bots_count`, { n: r.bots })}
                  </p>
                </div>
                <input
                  type="number"
                  min={0}
                  max={100}
                  inputMode="numeric"
                  aria-label={t(`${k}.quota_for`, { user: userLabel(r) })}
                  placeholder={t(`${k}.quota_default`, { n: def })}
                  value={draft}
                  onChange={(e) => setDrafts((d) => ({ ...d, [r.row_id]: e.target.value }))}
                  className={cn(inputCls, "w-40", !valid && "border-destructive")}
                />
                <button
                  type="button"
                  className={outlineBtn}
                  disabled={!valid || !changed || busy === r.row_id}
                  onClick={() => void save(r, parsed)}
                >
                  {busy === r.row_id && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
                  {t(`${k}.save`)}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ---------- registro ----------
function AuditTab({ t }: { t: T }) {
  const [rows, setRows] = useState<AuditRow[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`${apiBase()}/admin/telegram/audit?limit=200`)
      .then((r) => readJson<{ data: AuditRow[] }>(r))
      .then((data) => {
        if (!cancelled) setRows(data.data);
      })
      .catch(() => {
        if (!cancelled) setRows([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!rows) return <Loading t={t} />;
  if (rows.length === 0) {
    return (
      <p className="rounded-2xl border border-dashed border-border px-5 py-12 text-center text-sm text-muted-foreground">
        {t(`${k}.audit_empty`)}
      </p>
    );
  }
  const label = (action: string) => {
    const key = `${k}.audit.${action}`;
    const txt = t(key);
    return txt === key ? action : txt;
  };
  return (
    <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border bg-card/60">
      {rows.map((r) => {
        const details = Object.entries(r.payload || {})
          .filter(([, v]) => v !== null && v !== "")
          .map(([key, v]) => `${key}: ${String(v)}`)
          .join(" · ");
        return (
          <li key={r.id} className="flex flex-col gap-0.5 px-5 py-3 sm:flex-row sm:items-baseline sm:gap-4">
            <time className="shrink-0 text-xs tabular-nums text-muted-foreground sm:w-40" dateTime={r.ts || undefined}>
              {fullWhen(toMs(r.ts))}
            </time>
            <span className="text-sm font-medium">{label(r.action)}</span>
            <span className="min-w-0 truncate text-xs text-muted-foreground">
              {[r.user ? userLabel(r.user) : null, details].filter(Boolean).join(" · ")}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
