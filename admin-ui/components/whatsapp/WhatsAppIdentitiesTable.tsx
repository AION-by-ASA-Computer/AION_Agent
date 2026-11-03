"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RotateCcw, Unlink } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { readApiErrorMessage } from "@/lib/apiErrors";
import { cn } from "@/lib/cn";
import { fullWhen, shortWhen, toMs } from "@/lib/datetime";
import { useT } from "@/lib/i18n/use-t";
import { Note } from "@/components/settings/ui";
import { DeleteDialog } from "@/components/ui/ConfirmDialogs";
import { ghostBtn, outlineBtn } from "@/components/ui/classes";
import type { Notify } from "./WhatsAppConfigPanel";

const k = "admin_whatsapp.identities";
const th = "px-5 py-2 text-xs font-medium text-muted-foreground";
const td = "px-5 py-3 align-middle";

type Identity = {
  id: string | number;
  user_id: string | number;
  user_identifier: string;
  user_display_name: string | null;
  wa_profile_name: string | null;
  phone_hint: string | null;
  linked_at: string | null;
  last_inbound_at: string | null;
};

const ms = (v: string | null) => (v ? toMs(/(Z|[+-]\d\d:?\d\d)$/.test(v) ? v : `${v}Z`) : 0);

function When({ v }: { v: string | null }) {
  const at = ms(v);
  if (!at) return <span className="text-muted-foreground">—</span>;
  return (
    <time dateTime={new Date(at).toISOString()} title={fullWhen(at)} className="tabular-nums">
      {shortWhen(at)}
    </time>
  );
}

export function WhatsAppIdentitiesTable({ notify }: { notify: Notify }) {
  const t = useT();
  const [items, setItems] = useState<Identity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [target, setTarget] = useState<Identity | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/whatsapp/identities`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setItems(Array.isArray(data?.items) ? data.items : []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void load();
  }, [load]);

  const unlink = async () => {
    if (!target) return;
    setBusy(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/whatsapp/identities/${encodeURIComponent(String(target.id))}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await readApiErrorMessage(res));
      setItems((list) => list?.filter((i) => i.id !== target.id) ?? list);
      notify(t(`${k}.unlinked`, { name: target.user_identifier }), "success");
      setTarget(null);
    } catch (e) {
      notify(t(`${k}.unlink_failed`, { error: e instanceof Error ? e.message : "" }), "error");
    } finally {
      setBusy(false);
    }
  };

  const refresh = (
    <button type="button" className={outlineBtn} onClick={() => void load()} disabled={loading}>
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <RotateCcw className="h-3.5 w-3.5" aria-hidden />}
      {t(`${k}.refresh`)}
    </button>
  );

  if (!items) {
    if (loading) {
      return (
        <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t(`${k}.loading`)}
        </div>
      );
    }
    return (
      <div className="flex flex-col items-start gap-3">
        <Note tone="warn">{t(`${k}.failed`, { error: error || "" })}</Note>
        {refresh}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">{refresh}</div>
      {items.length === 0 ? (
        <Note>{t(`${k}.empty`)}</Note>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-border bg-card/60">
          <table className="w-full min-w-[44rem] text-sm">
            <thead>
              <tr className="border-b border-border/50 text-left">
                <th scope="col" className={th}>{t(`${k}.col.user`)}</th>
                <th scope="col" className={th}>{t(`${k}.col.wa_name`)}</th>
                <th scope="col" className={th}>{t(`${k}.col.phone`)}</th>
                <th scope="col" className={th}>{t(`${k}.col.linked`)}</th>
                <th scope="col" className={th}>{t(`${k}.col.last`)}</th>
                <th scope="col" className={cn(th, "text-right")}>
                  <span className="sr-only">{t(`${k}.col.actions`)}</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {items.map((i) => (
                <tr key={i.id} className="transition-colors hover:bg-secondary/40">
                  <td className={cn(td, "max-w-[16rem]")}>
                    <p className="truncate font-medium" title={i.user_display_name || i.user_identifier}>
                      {i.user_display_name || i.user_identifier}
                    </p>
                    {i.user_display_name && <p className="truncate text-xs text-muted-foreground">{i.user_identifier}</p>}
                  </td>
                  <td className={cn(td, "max-w-[12rem] truncate")}>{i.wa_profile_name || <span className="text-muted-foreground">—</span>}</td>
                  <td className={cn(td, "font-mono text-[12.5px]")}>{i.phone_hint || "—"}</td>
                  <td className={td}><When v={i.linked_at} /></td>
                  <td className={td}><When v={i.last_inbound_at} /></td>
                  <td className={cn(td, "text-right")}>
                    <button
                      type="button"
                      className={cn(ghostBtn, "hover:text-destructive")}
                      onClick={() => setTarget(i)}
                      aria-label={t(`${k}.unlink_label`, { name: i.user_identifier })}
                    >
                      <Unlink className="h-3.5 w-3.5" aria-hidden />
                      {t(`${k}.unlink`)}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {target && (
        <DeleteDialog
          name={target.user_identifier}
          busy={busy}
          ns={`${k}.delete`}
          t={t}
          onConfirm={() => void unlink()}
          onClose={() => !busy && setTarget(null)}
        />
      )}
    </div>
  );
}
