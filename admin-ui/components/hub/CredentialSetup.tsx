"use client";

import { useState } from "react";
import { AlertTriangle, Check, Copy, Loader2, Plus, Sparkles, Upload } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { dangerBtn, ghostBtn, outlineBtn, solidBtn } from "@/components/ui/classes";
import type { CredentialSchemaField } from "@/lib/mcpIntegrationPolicy";

const chipCls = "rounded-md bg-secondary px-1.5 py-0.5 font-mono text-[12px] text-foreground";

/** Fields found by discovery that the schema does not have yet. Adding never touches existing fields. */
export function SchemaSuggestion({
  suggested,
  current,
  onAdd,
}: {
  suggested: CredentialSchemaField[];
  current: CredentialSchemaField[];
  onAdd: (missing: CredentialSchemaField[]) => void;
}) {
  const t = useT();
  const have = new Set(current.map((f) => f.key));
  const missing = suggested.filter((f) => !have.has(f.key));
  if (missing.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 rounded-2xl bg-secondary/60 p-3.5" role="status">
      <p className="flex items-start gap-2 text-sm">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <span>{t("admin_hub.editors.suggest.body", { count: missing.length })}</span>
      </p>
      <ul className="flex flex-wrap gap-1.5" aria-label={t("admin_hub.editors.suggest.list")}>
        {missing.map((f) => (
          <li key={f.key} className={chipCls}>
            {f.key}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className={outlineBtn} onClick={() => onAdd(missing)}>
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t("admin_hub.editors.suggest.add", { count: missing.length })}
        </button>
        <span className="text-xs text-muted-foreground">{t("admin_hub.editors.suggest.note")}</span>
      </div>
    </div>
  );
}

/** Env placeholders for the registry: preview, copy, and a guarded write. */
export function RegistryEnvPanel({
  yaml,
  dirty,
  busy,
  overwriteKeys,
  onApply,
}: {
  yaml: string;
  /** Schema edited but not saved: the backend builds the env from the saved one. */
  dirty: boolean;
  busy: boolean;
  /** Keys in the yaml that already hold a value in the registry. */
  overwriteKeys: string[];
  onApply: () => void;
}) {
  const t = useT();
  const k = "admin_hub.editors.yaml";
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState(false);

  if (!yaml || yaml === "env: {}") return null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(yaml);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable */
    }
  };

  const apply = () => {
    if (overwriteKeys.length > 0 && !confirming) {
      setConfirming(true);
      return;
    }
    setConfirming(false);
    onApply();
  };

  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-border/70 p-3.5" aria-labelledby="registry-env-title">
      <div>
        <h3 id="registry-env-title" className="text-sm font-semibold">
          {t(`${k}.title`)}
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">{t(`${k}.body`)}</p>
      </div>

      <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-xl bg-secondary/60 p-3 font-mono text-xs leading-relaxed">{yaml}</pre>

      {dirty && (
        <p className="flex gap-2 rounded-xl bg-warning/12 px-3 py-2 text-xs" role="status">
          <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>{t(`${k}.dirty`)}</span>
        </p>
      )}

      {confirming ? (
        <div className="flex flex-col gap-2.5 rounded-xl border border-destructive/40 p-3" role="alertdialog" aria-label={t(`${k}.confirm_title`)}>
          <p className="text-sm">{t(`${k}.confirm_body`, { count: overwriteKeys.length })}</p>
          <ul className="flex flex-wrap gap-1.5">
            {overwriteKeys.map((key) => (
              <li key={key} className={chipCls}>
                {key}
              </li>
            ))}
          </ul>
          <div className="flex justify-end gap-2">
            <button type="button" className={ghostBtn} autoFocus onClick={() => setConfirming(false)}>
              {t(`${k}.cancel`)}
            </button>
            <button type="button" className={dangerBtn} disabled={busy} onClick={apply}>
              {t(`${k}.replace`)}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <button type="button" onClick={() => void copy()} className={cn(ghostBtn, "px-2.5")}>
            {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
            <span role="status">{copied ? t(`${k}.copied`) : t(`${k}.copy`)}</span>
          </button>
          <button type="button" className={solidBtn} disabled={busy || dirty} onClick={apply}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Upload className="h-3.5 w-3.5" aria-hidden />}
            {t(`${k}.apply`)}
          </button>
        </div>
      )}
    </section>
  );
}
