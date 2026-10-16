"use client";

import { Copy, Check, Download, AlertTriangle } from "lucide-react";
import { Dialog } from "@/components/profiles/Dialog";
import { outlineBtn, solidBtn } from "@/components/ui/classes";
import { useState } from "react";

interface TempPassword {
  user_id: string;
  identifier: string;
  email: string | null;
  password?: string;
  expires_at?: string;
}

interface Props {
  isOpen: boolean;
  onClose: () => void;
  passwords: TempPassword[];
  title?: string;
  message?: string;
}

export function TempPasswordsDialog({ isOpen, onClose, passwords, title, message }: Props) {
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  const handleCopy = () => {
    const text = passwords.map(p => `${p.identifier} (${p.email || 'no email'}): ${p.password}`).join("\n");
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const csvContent = "data:text/csv;charset=utf-8," 
      + "Identifier,Email,Password,ExpiresAt\n"
      + passwords.map(e => `${e.identifier},${e.email || ''},${e.password},${e.expires_at || ''}`).join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "temp_passwords.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <Dialog title={title || "Password temporanee"} closeLabel="Chiudi" onClose={onClose} className="max-w-2xl">
      <div className="flex flex-col gap-4">
        {message && (
          <div className="flex items-start gap-3 rounded-2xl bg-warning/10 px-4 py-3 text-sm" role="alert">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
            <div className="leading-relaxed">{message}</div>
          </div>
        )}

        <ul className="-mx-1 flex max-h-72 flex-col overflow-y-auto px-1">
          {passwords.map((p, i) => (
            <li key={i} className="flex flex-col gap-2 border-b border-border/40 py-3 last:border-b-0 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{p.identifier}</div>
                {p.email && <div className="truncate text-xs text-muted-foreground">{p.email}</div>}
                {p.expires_at && <div className="mt-0.5 text-xs tabular-nums text-muted-foreground">Scade: {new Date(p.expires_at).toLocaleString()}</div>}
              </div>
              <code className="shrink-0 select-all rounded-lg border border-border bg-background px-3 py-1.5 font-mono text-sm">{p.password}</code>
            </li>
          ))}
        </ul>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs font-medium text-destructive sm:max-w-sm">
            Queste password vengono mostrate una sola volta. Copiale o scaricale ora.
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={handleCopy} className={outlineBtn}>
              {copied ? <Check className="h-3.5 w-3.5 text-success" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />} Copia tutte
            </button>
            <button type="button" onClick={handleDownload} className={solidBtn}>
              <Download className="h-3.5 w-3.5" aria-hidden /> CSV
            </button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
