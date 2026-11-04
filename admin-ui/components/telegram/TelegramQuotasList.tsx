"use client";

/**
 * "Quotas" section of the admin Telegram page: per-user cap on assistants for every
 * user who linked Telegram. An empty field falls back to the default quota
 * (`max_bots_per_user`, edited in the Configuration section above).
 * Backed by `GET /admin/telegram/quotas` and `PUT /admin/telegram/quotas/{user}`.
 */

import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { inputCls, outlineBtn } from "@/components/ui/classes";
import { EmptyList, Loading, k, readJson, userLabel, type Notify, type T, type UserRef } from "./shared";

type QuotaRow = UserRef & { linked: boolean; bots: number; max_bots: number | null };

/**
 * @param rev bumped by the page after the Telegram config is saved, so the default
 *            quota shown in the placeholders follows the new value.
 */
export function TelegramQuotasList({ t, notify, rev }: { t: T; notify: Notify; rev: number }) {
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
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount / config save
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev]);

  /** Persist one user's quota; `null` resets it to the default. */
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
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">{t(`${k}.quota_hint`, { n: def })}</p>
      {rows.length === 0 ? (
        <EmptyList>{t(`${k}.quota_empty`)}</EmptyList>
      ) : (
        <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border bg-card/60">
          {rows.map((r) => {
            const draft = drafts[r.row_id] ?? (r.max_bots == null ? "" : String(r.max_bots));
            const parsed = draft.trim() === "" ? null : Number(draft);
            // Same bounds the backend enforces (0–100, integers); empty means "use default".
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
    </div>
  );
}
