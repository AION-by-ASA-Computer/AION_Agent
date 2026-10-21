"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { getLocale } from "@/lib/i18n/i18n-store";
import { useT } from "@/lib/i18n/use-t";
import { ChoiceList, Note } from "@/components/settings/ui";
import { inputCls, solidBtn } from "@/components/ui/classes";
import { cn } from "@/lib/cn";
import type { ToastState } from "@/components/PageToast";

const k = "admin_users.signup_policy";
const POLICIES = ["open", "allowlist", "closed"] as const;
type Policy = (typeof POLICIES)[number];

interface SignupPolicy {
  policy: Policy;
  allowlist: string[];
  applies: boolean;
  max_entries: number;
}

const parseEntries = (text: string) =>
  text
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);

/** Who can get a new account at their first single sign-on: everyone, only listed emails/domains, or nobody. */
export function SignupPolicyPanel({ onToast }: { onToast: (toast: ToastState) => void }) {
  const t = useT();
  const [saved, setSaved] = useState<SignupPolicy | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [policy, setPolicy] = useState<Policy>("open");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apply = useCallback((data: SignupPolicy) => {
    setSaved(data);
    setPolicy(data.policy);
    setText(data.allowlist.join("\n"));
  }, []);

  useEffect(() => {
    apiFetch(`${apiBase()}/admin/auth/signup-policy`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then(apply)
      .catch(() => setLoadFailed(true));
  }, [apply]);

  const entries = useMemo(() => parseEntries(text), [text]);
  const dirty = !!saved && (policy !== saved.policy || entries.join("\n") !== saved.allowlist.join("\n"));

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/auth/signup-policy`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ policy, allowlist: entries }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data?.detail ?? {};
        if (detail.code === "invalid_allowlist_entry") setError(t(`${k}.error.invalid_entry`, { entry: detail.entry }));
        else if (detail.code === "allowlist_too_long") setError(t(`${k}.error.too_long`, { max: detail.max }));
        else setError(t(`${k}.error.generic`));
        return;
      }
      apply(data);
      onToast({ message: t(`${k}.saved`), variant: "success" });
    } catch {
      setError(t(`${k}.error.generic`));
    } finally {
      setSaving(false);
    }
  };

  if (loadFailed) return <p className="text-sm text-destructive">{t(`${k}.error.load`)}</p>;
  if (!saved) return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />;

  const count = t(`${k}.count_${new Intl.PluralRules(getLocale()).select(entries.length) === "one" ? "one" : "other"}`, { count: entries.length });

  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-hidden rounded-2xl border border-border/70 bg-card">
        <ChoiceList<Policy>
          value={policy}
          onChange={setPolicy}
          label={t(`${k}.label`)}
          options={POLICIES.map((p) => ({ value: p, title: t(`${k}.${p}.title`), description: t(`${k}.${p}.description`) }))}
        />
        {policy === "allowlist" && (
          <div className="flex flex-col gap-2 border-t border-border/40 px-5 py-4">
            <div className="flex items-baseline justify-between gap-3">
              <label htmlFor="signup-allowlist" className="text-sm font-medium">
                {t(`${k}.list_label`)}
              </label>
              <span className="text-xs tabular-nums text-muted-foreground">{count}</span>
            </div>
            <textarea
              id="signup-allowlist"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={6}
              spellCheck={false}
              autoCapitalize="off"
              placeholder={"mario.rossi@azienda.it\n@team.azienda.it"}
              aria-describedby="signup-allowlist-hint"
              className={cn(inputCls, "h-auto min-h-[8rem] resize-y py-2.5 font-mono text-[13px] leading-relaxed")}
            />
            <p id="signup-allowlist-hint" className="text-xs text-muted-foreground">
              {t(`${k}.list_hint`)}
            </p>
          </div>
        )}
      </div>

      {policy === "allowlist" && entries.length === 0 && <Note tone="warn">{t(`${k}.empty_warning`)}</Note>}
      {error && (
        <p className="px-1 text-xs text-destructive" role="alert">
          {error}
        </p>
      )}

      <div>
        <button type="button" className={solidBtn} disabled={!dirty || saving} onClick={save}>
          {saving && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
          {saving ? t(`${k}.saving`) : t(`${k}.save`)}
        </button>
      </div>
    </div>
  );
}
