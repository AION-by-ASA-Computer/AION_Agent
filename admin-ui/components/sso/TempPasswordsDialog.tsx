"use client";

import { useState } from "react";
import { AlertTriangle, Check, Copy, Download } from "lucide-react";
import { Dialog } from "@/components/profiles/Dialog";
import { outlineBtn, solidBtn } from "@/components/ui/classes";
import { getLocale } from "@/lib/i18n/i18n-store";

type T = (key: string, vars?: Record<string, string | number>) => string;

/** Temporary password issued when SMTP is not configured: the backend returns it once and never again. */
export interface TempPassword {
  user_id?: string;
  identifier: string;
  email?: string | null;
  password: string;
  expires_at?: string | null;
}

const k = "admin_users.temp_password";

const formatDate = (iso: string) => new Date(iso).toLocaleString(getLocale(), { dateStyle: "medium", timeStyle: "short" });

const csvCell = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);

export function TempPasswordsDialog({ passwords, t, onClose }: { passwords: TempPassword[]; t: T; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const many = passwords.length > 1;

  const copy = async () => {
    const text = many ? passwords.map((p) => `${p.identifier}: ${p.password}`).join("\n") : passwords[0]?.password ?? "";
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable (insecure context): the password stays selectable on screen.
    }
  };

  const download = () => {
    const rows = [["identifier", "email", "password", "expires_at"], ...passwords.map((p) => [p.identifier, p.email ?? "", p.password, p.expires_at ?? ""])];
    const blob = new Blob([rows.map((r) => r.map(csvCell).join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "temp_passwords.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Dialog title={t(`${k}.${many ? "title_many" : "title"}`)} closeLabel={t(`${k}.close`)} onClose={onClose} className="max-w-xl">
      <div className="flex flex-col gap-4">
        <div className="flex items-start gap-3 rounded-2xl bg-warning/10 px-4 py-3 text-sm" role="alert">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
          <p className="leading-relaxed">{t(`${k}.body`)}</p>
        </div>

        <ul className="-mx-1 flex max-h-72 flex-col overflow-y-auto px-1">
          {passwords.map((p) => (
            <li
              key={p.user_id ?? p.identifier}
              className="flex flex-col gap-2 border-b border-border/40 py-3 last:border-b-0 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
            >
              <div className="min-w-0">
                <div className="truncate font-mono text-sm font-medium">{p.identifier}</div>
                {p.email && <div className="truncate text-xs text-muted-foreground">{p.email}</div>}
                {p.expires_at && <div className="mt-0.5 text-xs tabular-nums text-muted-foreground">{t(`${k}.expires`, { date: formatDate(p.expires_at) })}</div>}
              </div>
              <code className="shrink-0 select-all rounded-lg border border-border bg-background px-3 py-1.5 font-mono text-sm">{p.password}</code>
            </li>
          ))}
        </ul>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs font-medium text-destructive sm:max-w-sm">{t(`${k}.once`)}</p>
          <div className="flex gap-2">
            <button type="button" onClick={() => void copy()} className={outlineBtn}>
              {copied ? <Check className="h-3.5 w-3.5 text-success" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
              {t(`${k}.${copied ? "copied" : many ? "copy_all" : "copy"}`)}
            </button>
            {many ? (
              <button type="button" onClick={download} className={solidBtn}>
                <Download className="h-3.5 w-3.5" aria-hidden /> CSV
              </button>
            ) : (
              <button type="button" onClick={onClose} className={solidBtn}>
                {t(`${k}.done`)}
              </button>
            )}
          </div>
        </div>
      </div>
    </Dialog>
  );
}
