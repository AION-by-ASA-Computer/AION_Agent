"use client";

/**
 * One-time reveal of a freshly created service account API key.
 *
 * `POST /admin/service-accounts/{id}/keys` is the only response that carries
 * the full secret (the DB keeps just its SHA-256), so this dialog insists that
 * the admin copies it now. Closing it drops the secret from memory for good.
 */

import { useState } from "react";
import { AlertTriangle, Check, Copy } from "lucide-react";
import { Dialog } from "@/components/profiles/Dialog";
import { outlineBtn, solidBtn } from "@/components/ui/classes";
import { formatDate, k, type CreatedKey, type T } from "./shared";

/** @param created Key returned by the create call, including its `key` secret. */
export function NewKeyDialog({ created, t, onClose }: { created: CreatedKey; t: T; onClose: () => void }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable (insecure context): the key stays selectable on screen.
    }
  };

  return (
    <Dialog title={t(`${k}.new_key.title`)} closeLabel={t(`${k}.new_key.done`)} onClose={onClose} className="max-w-xl">
      <div className="flex flex-col gap-4">
        <div className="flex items-start gap-3 rounded-2xl bg-warning/10 px-4 py-3 text-sm" role="alert">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
          <p className="leading-relaxed">{t(`${k}.new_key.body`)}</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium">{created.name}</span>
          <code className="block select-all break-all rounded-xl border border-border bg-background px-3.5 py-2.5 font-mono text-sm">{created.key}</code>
          {created.expires_at && <span className="text-xs tabular-nums text-muted-foreground">{t(`${k}.keys.expires_on`, { date: formatDate(created.expires_at) })}</span>}
        </div>

        <p className="text-xs text-muted-foreground">
          {t(`${k}.new_key.usage`)} <code className="rounded bg-secondary px-1 py-0.5 font-mono">Authorization: Bearer aion_…</code>{" "}
          {t(`${k}.new_key.usage_or`)} <code className="rounded bg-secondary px-1 py-0.5 font-mono">X-Api-Key</code>
        </p>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs font-medium text-destructive sm:max-w-xs">{t(`${k}.new_key.once`)}</p>
          <div className="flex gap-2">
            <button type="button" onClick={() => void copy()} className={outlineBtn} autoFocus>
              {copied ? <Check className="h-3.5 w-3.5 text-success" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
              {t(`${k}.new_key.${copied ? "copied" : "copy"}`)}
            </button>
            <button type="button" onClick={onClose} className={solidBtn}>
              {t(`${k}.new_key.done`)}
            </button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
