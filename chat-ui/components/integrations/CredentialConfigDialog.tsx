"use client";

import { useMemo, useState } from "react";
import { Plug, Plus, X } from "lucide-react";

import type { CredentialField, Integration } from "@/components/integrations/types";
import { apiBase } from "@/lib/config";
import { jsonHeaders } from "@/lib/api/aion";
import { useT } from "@/lib/i18n/use-t";

const inputClass =
  "focus-ring w-full rounded-xl border border-input bg-background px-3 py-2.5 text-sm";

export function CredentialConfigDialog({
  integration,
  userId,
  token,
  onClose,
}: {
  integration: Integration;
  userId: string;
  token: string | null;
  onClose: () => void;
}) {
  const t = useT();
  const [values, setValues] = useState<Record<string, string>>({});
  const [customFields, setCustomFields] = useState<
    Array<{ id: string; key: string; label: string; type: "text" | "password" }>
  >([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasOAuthToken = useMemo(
    () => integration.credentials_hints.some((h) => h.key === "OAUTH_TOKEN" && !h.is_expired),
    [integration.credentials_hints],
  );

  const placeholders: Record<string, string> = {};
  integration.credentials_hints.forEach((h) => {
    placeholders[h.key] = h.display_hint ? `(${h.display_hint})` : "(saved)";
  });

  const formFields = useMemo(() => {
    const seen = new Set<string>();
    const out: CredentialField[] = [];
    for (const f of integration.credential_schema) {
      if (!f.key || seen.has(f.key)) continue;
      seen.add(f.key);
      out.push(f);
    }
    for (const c of customFields) {
      const key = normalizeKey(c.key);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push({
        key,
        label: c.label.trim() || key,
        type: c.type,
        required: false,
      });
    }
    return out;
  }, [integration.credential_schema, customFields]);

  function getOAuthButtonText() {
    const provider = integration.oauth_provider || "oauth2";
    const map: Record<string, string> = {
      google: t("integrationsPage.oauth_login_google"),
      github: t("integrationsPage.oauth_login_github"),
      microsoft: t("integrationsPage.oauth_login_microsoft"),
      auth0: t("integrationsPage.oauth_login_auth0"),
    };
    const label = provider.charAt(0).toUpperCase() + provider.slice(1);
    return map[provider.toLowerCase()] || t("integrationsPage.oauth_login_generic", { provider: label });
  }

  async function handleOAuthLogin() {
    const redirectUri = `${apiBase()}/v1/integrations/oauth/callback`;
    try {
      const res = await fetch(
        `${apiBase()}/v1/integrations/oauth/start?server_slug=${encodeURIComponent(integration.server_slug)}&redirect_uri=${encodeURIComponent(redirectUri)}`,
        { headers: jsonHeaders(userId, token) },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setError((err as { detail?: string }).detail || t("integrationsPage.oauth_start_error"));
        return;
      }
      const data = (await res.json()) as { authorization_url: string; state: string };
      localStorage.setItem("oauth_state", data.state);
      localStorage.setItem("oauth_server_slug", integration.server_slug);
      window.location.href = data.authorization_url;
    } catch {
      setError(t("integrationsPage.oauth_network_error"));
    }
  }

  function addCustomField() {
    setCustomFields((prev) => [
      ...prev,
      {
        id: `cf-${Date.now()}-${prev.length}`,
        key: `CUSTOM_${prev.length + 1}`,
        label: t("integrationsPage.new_field_label"),
        type: "password",
      },
    ]);
  }

  function normalizeKey(raw: string) {
    return raw.trim().toUpperCase().replace(/\s+/g, "_");
  }

  async function save() {
    const missing = formFields.filter(
      (f) => f.required && !values[f.key]?.trim() && !placeholders[f.key],
    );
    if (missing.length) {
      setError(`${t("integrationsPage.field_error")}: ${missing.map((f) => f.label).join(", ")}`);
      return;
    }

    const toSave: Record<string, string> = {};
    const hints: Record<string, string> = {};
    for (const [key, val] of Object.entries(values)) {
      if (!val.trim()) continue;
      toSave[key] = val;
      const field = formFields.find((f) => f.key === key);
      if (field?.type === "password" || field?.type === "oauth") {
        hints[key] = val.length > 4 ? `${val.slice(0, 4)}…` : "****";
      } else {
        hints[key] = val.length > 20 ? `${val.slice(0, 20)}…` : val;
      }
    }

    if (Object.keys(toSave).length === 0) {
      onClose();
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase()}/v1/integrations/credentials`, {
        method: "POST",
        headers: jsonHeaders(userId, token),
        body: JSON.stringify({
          server_slug: integration.server_slug,
          credentials: toSave,
          display_hints: hints,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || t("integrationsPage.save_error"));
      }
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("integrationsPage.save_error"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4 backdrop-blur-[2px]">
      <div className="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-border/80 bg-background/95 shadow-2xl backdrop-blur-xl">
        <div className="p-6">
          <div className="mb-5 flex items-start gap-3">
            {integration.icon_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={integration.icon_url}
                alt=""
                className="h-11 w-11 shrink-0 rounded-2xl border border-border/60 object-cover"
              />
            ) : (
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
                <Plug className="h-5 w-5" aria-hidden />
              </div>
            )}
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold tracking-tight">{integration.display_name}</h2>
              {integration.description ? (
                <p className="mt-0.5 text-xs text-muted-foreground">{integration.description}</p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="focus-ring rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label={t("integrationsPage.cancel")}
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <p className="mb-5 rounded-2xl border border-border/60 bg-muted/30 px-4 py-3 text-xs leading-relaxed text-muted-foreground">
            {t("integrationsPage.security")}
          </p>

          <div className="space-y-5">
            {integration.has_oauth ? (
              <div className="rounded-2xl border border-primary/20 bg-primary/5 p-4 text-center">
                <h3 className="mb-2 text-sm font-semibold">{t("integrationsPage.oauth_title")}</h3>
                {hasOAuthToken ? (
                  <>
                    <p className="mb-4 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                      {t("integrationsPage.oauth_connected")}
                    </p>
                    <button
                      type="button"
                      onClick={handleOAuthLogin}
                      className="focus-ring flex w-full items-center justify-center gap-2 rounded-xl border border-border/70 bg-background/60 px-4 py-2.5 text-sm font-semibold transition hover:bg-muted"
                    >
                      <Plug className="h-4 w-4" aria-hidden />
                      {t("integrationsPage.oauth_reconnect")}
                    </button>
                  </>
                ) : (
                  <>
                    <p className="mb-4 text-xs text-muted-foreground">
                      {t("integrationsPage.oauth_intro")}
                    </p>
                    <button
                      type="button"
                      onClick={handleOAuthLogin}
                      className="focus-ring flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90"
                    >
                      <Plug className="h-4 w-4" aria-hidden />
                      {getOAuthButtonText()}
                    </button>
                  </>
                )}
              </div>
            ) : null}

            {formFields.map((field) => {
              const custom = customFields.find((c) => normalizeKey(c.key) === field.key);
              const isCustom = Boolean(custom);
              return (
                <div key={isCustom ? custom!.id : field.key}>
                  <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {isCustom ? custom!.label || field.label : field.label}
                    {field.required ? <span className="ml-1 text-destructive">*</span> : null}
                    {isCustom ? (
                      <span className="ml-2 font-normal normal-case">
                        ({t("integrationsPage.custom_field")})
                      </span>
                    ) : null}
                  </label>
                  {field.description ? (
                    <p className="mb-1.5 text-xs text-muted-foreground">{field.description}</p>
                  ) : null}
                  {isCustom && custom ? (
                    <div className="mb-2 grid grid-cols-2 gap-2">
                      <input
                        className="focus-ring rounded-xl border border-input bg-background px-2 py-1.5 font-mono text-xs"
                        value={custom.key}
                        onChange={(e) => {
                          const nextKey = normalizeKey(e.target.value);
                          setCustomFields((prev) =>
                            prev.map((c) => (c.id === custom.id ? { ...c, key: nextKey } : c)),
                          );
                          setValues((v) => {
                            const old = v[field.key];
                            if (old === undefined) return v;
                            const { [field.key]: _removed, ...rest } = v;
                            return nextKey ? { ...rest, [nextKey]: old } : rest;
                          });
                        }}
                        placeholder="API_KEY"
                      />
                      <input
                        className="focus-ring rounded-xl border border-input bg-background px-2 py-1.5 text-xs"
                        value={custom.label}
                        onChange={(e) => {
                          setCustomFields((prev) =>
                            prev.map((c) => (c.id === custom.id ? { ...c, label: e.target.value } : c)),
                          );
                        }}
                        placeholder={t("integrationsPage.field_label")}
                      />
                    </div>
                  ) : null}
                  {field.type === "oauth" ? (
                    <div className="space-y-1">
                      <p className="text-xs text-muted-foreground">{t("integrationsPage.pat_hint")}</p>
                      <input
                        type="password"
                        value={values[field.key] || ""}
                        onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
                        placeholder={placeholders[field.key] || t("integrationsPage.pat_placeholder")}
                        className={inputClass}
                      />
                    </div>
                  ) : (
                    <input
                      type={field.type === "password" ? "password" : "text"}
                      value={values[field.key] || ""}
                      onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
                      placeholder={placeholders[field.key] || field.label}
                      className={inputClass}
                    />
                  )}
                </div>
              );
            })}

            {!integration.has_oauth ? (
              <button
                type="button"
                onClick={addCustomField}
                className="focus-ring flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-border/80 py-3 text-sm text-muted-foreground transition hover:bg-muted/40 hover:text-foreground"
              >
                <Plus className="h-4 w-4" aria-hidden />
                {t("integrationsPage.add_credential")}
              </button>
            ) : null}
          </div>

          {error ? (
            <div className="mt-5 rounded-2xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          ) : null}

          <div className="mt-6 flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="focus-ring rounded-xl border border-border/70 px-4 py-2 text-sm font-medium transition hover:bg-muted"
            >
              {t("integrationsPage.cancel")}
            </button>
            {(!integration.has_oauth || formFields.length > 0) && (
              <button
                type="button"
                onClick={() => void save()}
                disabled={saving}
                className="focus-ring rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90 disabled:opacity-50"
              >
                {saving ? t("integrationsPage.saving") : t("integrationsPage.save")}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
