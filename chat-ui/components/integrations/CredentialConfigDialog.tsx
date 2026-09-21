"use client";

import { useMemo, useState } from "react";
import {
  ChevronDown,
  Eye,
  EyeOff,
  Plug,
  Plus,
  SlidersHorizontal,
  X,
} from "lucide-react";

import type { CredentialField, Integration } from "@/components/integrations/types";
import { apiBase, oauthCallbackRedirectUri } from "@/lib/config";
import { jsonHeaders } from "@/lib/api/aion";
import { oauthManagedFieldKeys, oauthProviderDisplayName } from "@/lib/integrations/oauthLabels";
import {
  formatFieldLabel,
  isAdvancedField,
  isBooleanField,
  isSecretField,
} from "@/lib/integrations/field-labels";
import { Switch } from "@/components/ui/Switch";
import { useT } from "@/lib/i18n/use-t";

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
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});
  const [customFields, setCustomFields] = useState<
    Array<{ id: string; key: string; label: string; type: "text" | "password" | "boolean" }>
  >([]);
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);
  const [attemptedSave, setAttemptedSave] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const oauthManaged = oauthManagedFieldKeys();
  const providerLabel = oauthProviderDisplayName(integration);

  const hasOAuthToken = useMemo(
    () => integration.credentials_hints.some((h) => h.key === "OAUTH_TOKEN" && !h.is_expired),
    [integration.credentials_hints],
  );

  const placeholders: Record<string, string> = {};
  integration.credentials_hints.forEach((h) => {
    placeholders[h.key] = h.display_hint ? `(${h.display_hint})` : "(salvato)";
  });

  const formFields = useMemo(() => {
    const seen = new Set<string>();
    const out: CredentialField[] = [];
    for (const f of integration.credential_schema) {
      if (!f.key || seen.has(f.key)) continue;
      if (integration.has_oauth && oauthManaged.has(f.key)) continue;
      seen.add(f.key);
      out.push(f);
    }
    for (const c of customFields) {
      const key = normalizeKey(c.key);
      if (!key || seen.has(key)) continue;
      if (integration.has_oauth && oauthManaged.has(key)) continue;
      seen.add(key);
      out.push({
        key,
        label: c.label.trim() || key,
        type: c.type,
        category: "basic",
        required: false,
      });
    }
    return out;
  }, [integration.credential_schema, integration.has_oauth, customFields, oauthManaged]);

  const { basicFields, advancedFields } = useMemo(() => {
    const basic: CredentialField[] = [];
    const adv: CredentialField[] = [];

    for (const f of formFields) {
      if (isAdvancedField(f)) {
        adv.push(f);
      } else {
        basic.push(f);
      }
    }
    return { basicFields: basic, advancedFields: adv };
  }, [formFields]);

  function getOAuthButtonText() {
    return t("integrationsPage.oauth_login_service", { service: providerLabel });
  }

  async function handleOAuthLogin() {
    const redirectUri = oauthCallbackRedirectUri();
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

  function toggleShowPassword(key: string) {
    setShowPasswords((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  function getBooleanValue(key: string, defaultValue?: string | boolean): boolean {
    if (values[key] !== undefined) {
      return values[key] === "true";
    }
    if (placeholders[key]) {
      const p = placeholders[key].toLowerCase();
      if (p.includes("true")) return true;
      if (p.includes("false")) return false;
    }
    if (defaultValue !== undefined) {
      return defaultValue === true || defaultValue === "true";
    }
    return false;
  }

  function isFieldMissing(f: CredentialField): boolean {
    if (!f.required) return false;
    if (isBooleanField(f)) return false;
    const val = values[f.key]?.trim();
    const hasSaved = Boolean(placeholders[f.key]);
    return !val && !hasSaved;
  }

  async function save() {
    setAttemptedSave(true);
    const missing = formFields.filter(isFieldMissing);
    if (missing.length) {
      setError(
        `${t("integrationsPage.field_error")}: ${missing.map((f) => formatFieldLabel(f.key, f.label)).join(", ")}`,
      );
      return;
    }

    const toSave: Record<string, string> = {};
    const hints: Record<string, string> = {};

    for (const [key, val] of Object.entries(values)) {
      if (val === undefined || val === null || val === "") continue;
      toSave[key] = val;
      const field = formFields.find((f) => f.key === key);
      const isBool = field && isBooleanField(field);
      const isSec = field && isSecretField(field);

      if (isBool) {
        hints[key] = val === "true" ? "Attivo" : "Disattivo";
      } else if (isSec) {
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

  const oauthOnly = integration.has_oauth && formFields.length === 0;
  const showSaveButton = !oauthOnly && formFields.length > 0;

  function renderField(field: CredentialField) {
    const custom = customFields.find((c) => normalizeKey(c.key) === field.key);
    const isCustom = Boolean(custom);
    const labelText = isCustom ? custom!.label || field.label : formatFieldLabel(field.key, field.label);
    const isBool = isBooleanField(field);
    const isSecret = isSecretField(field);
    const showPlain = showPasswords[field.key];
    const missing = attemptedSave && isFieldMissing(field);

    if (isBool) {
      const checked = getBooleanValue(field.key, field.default_value);
      return (
        <div
          key={field.key}
          className="rounded-2xl border border-border/80 bg-card/60 p-4 sm:p-5 transition hover:border-primary/40 hover:bg-card shadow-sm"
        >
          <Switch
            id={`field-${field.key}`}
            checked={checked}
            onChange={(nextChecked) =>
              setValues((v) => ({ ...v, [field.key]: nextChecked ? "true" : "false" }))
            }
            label={
              <span className="text-sm font-semibold text-foreground">
                {labelText}
              </span>
            }
            description={field.description || undefined}
          />
        </div>
      );
    }

    return (
      <div
        key={isCustom ? custom!.id : field.key}
        className="rounded-2xl border border-border/80 bg-card/60 p-4 sm:p-5 transition hover:border-primary/40 hover:bg-card shadow-sm space-y-2.5"
      >
        {/* Label & Variable Name Header */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label
            htmlFor={`field-${field.key}`}
            className="text-sm font-bold text-foreground flex items-center gap-1.5"
          >
            <span>{labelText}</span>
            {field.required ? (
              <span className="text-red-500 font-bold" title="Obbligatorio">
                *
              </span>
            ) : null}
            {isCustom ? (
              <span className="font-normal text-muted-foreground text-xs">
                ({t("integrationsPage.custom_field")})
              </span>
            ) : null}
          </label>

          {field.key && !isCustom && (
            <span className="text-xs font-mono font-semibold text-primary/80 bg-primary/10 px-2.5 py-0.5 rounded-lg border border-primary/20">
              {field.key}
            </span>
          )}
        </div>

        {/* Optional Description */}
        {field.description ? (
          <p className="text-xs text-muted-foreground leading-relaxed">
            {field.description}
          </p>
        ) : null}

        {/* Custom Field Key/Label inputs */}
        {isCustom && custom ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">
                Nome Variabile ENV
              </label>
              <input
                className="w-full rounded-xl border border-input bg-background px-3.5 py-2.5 font-mono text-xs font-semibold text-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition"
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
                placeholder="ES: API_KEY"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">
                Etichetta
              </label>
              <input
                className="w-full rounded-xl border border-input bg-background px-3.5 py-2.5 text-xs text-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition"
                value={custom.label}
                onChange={(e) => {
                  setCustomFields((prev) =>
                    prev.map((c) => (c.id === custom.id ? { ...c, label: e.target.value } : c)),
                  );
                }}
                placeholder={t("integrationsPage.field_label")}
              />
            </div>
          </div>
        ) : null}

        {/* Input Controls */}
        {field.type === "oauth" ? (
          <div className="relative pt-1">
            <input
              id={`field-${field.key}`}
              type={showPlain ? "text" : "password"}
              value={values[field.key] || ""}
              onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
              placeholder={placeholders[field.key] || "Inserisci il Personal Access Token..."}
              className={`w-full rounded-xl border bg-background px-4 py-3 pr-12 text-sm text-foreground font-mono placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition ${
                missing ? "border-red-500 ring-2 ring-red-500/20" : "border-input"
              }`}
            />
            <button
              type="button"
              onClick={() => toggleShowPassword(field.key)}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-2 rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground transition cursor-pointer"
              tabIndex={-1}
              aria-label={showPlain ? "Nascondi" : "Mostra"}
            >
              {showPlain ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        ) : isSecret ? (
          <div className="relative pt-1">
            <input
              id={`field-${field.key}`}
              type={showPlain ? "text" : "password"}
              value={values[field.key] || ""}
              onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
              placeholder={placeholders[field.key] || `Inserisci ${labelText.toLowerCase()}...`}
              className={`w-full rounded-xl border bg-background px-4 py-3 pr-12 text-sm text-foreground font-mono placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition ${
                missing ? "border-red-500 ring-2 ring-red-500/20" : "border-input"
              }`}
            />
            <button
              type="button"
              onClick={() => toggleShowPassword(field.key)}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-2 rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground transition cursor-pointer"
              tabIndex={-1}
              aria-label={showPlain ? "Nascondi" : "Mostra"}
            >
              {showPlain ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        ) : (
          <div className="pt-1">
            <input
              id={`field-${field.key}`}
              type="text"
              value={values[field.key] || ""}
              onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
              placeholder={placeholders[field.key] || `Inserisci ${labelText.toLowerCase()}...`}
              className={`w-full rounded-xl border bg-background px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition ${
                missing ? "border-red-500 ring-2 ring-red-500/20" : "border-input"
              }`}
            />
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 sm:p-6 backdrop-blur-sm">
      <div className="max-h-[90vh] w-full max-w-3xl flex flex-col rounded-3xl border border-border bg-card text-card-foreground shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border p-6 bg-muted/20 shrink-0">
          <div className="flex items-center gap-4 min-w-0 pr-4">
            {integration.icon_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={integration.icon_url}
                alt=""
                className="h-12 w-12 shrink-0 rounded-2xl border border-border object-cover shadow-sm"
              />
            ) : (
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-primary/25 bg-primary/10 text-primary shadow-sm">
                <Plug className="h-6 w-6" aria-hidden />
              </div>
            )}
            <div className="min-w-0 flex-1">
              <h2 className="text-xl font-bold tracking-tight text-foreground truncate">
                {integration.display_name}
              </h2>
              {integration.description ? (
                <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
                  {integration.description}
                </p>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-2xl p-2.5 text-muted-foreground hover:bg-muted hover:text-foreground transition cursor-pointer shrink-0"
            aria-label={t("integrationsPage.cancel")}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Scrollable Form Body */}
        <div className="flex-1 overflow-y-auto p-6 sm:p-7 space-y-5 bg-background">
          {/* OAuth Banner if applicable */}
          {integration.has_oauth ? (
            <div className="rounded-2xl border border-primary/30 bg-primary/5 p-5 text-center space-y-3">
              <h3 className="text-base font-bold text-foreground">
                {t("integrationsPage.oauth_title_service", { service: providerLabel })}
              </h3>
              {hasOAuthToken ? (
                <>
                  <p className="text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                    {t("integrationsPage.oauth_connected_service", { service: providerLabel })}
                  </p>
                  <button
                    type="button"
                    onClick={handleOAuthLogin}
                    className="inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-background px-4 py-2.5 text-xs font-bold text-foreground transition hover:bg-muted cursor-pointer"
                  >
                    <Plug className="h-4 w-4" aria-hidden />
                    {t("integrationsPage.oauth_reconnect")}
                  </button>
                </>
              ) : (
                <>
                  <p className="text-xs text-muted-foreground max-w-md mx-auto">
                    {t("integrationsPage.oauth_intro_service", { service: providerLabel })}
                  </p>
                  <button
                    type="button"
                    onClick={handleOAuthLogin}
                    className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-xs font-bold text-primary-foreground shadow-md transition hover:bg-primary/90 cursor-pointer"
                  >
                    <Plug className="h-4 w-4" aria-hidden />
                    {getOAuthButtonText()}
                  </button>
                </>
              )}
            </div>
          ) : null}

          {/* Primary Variables (1 row per variable) */}
          {basicFields.length > 0 ? (
            <div className="space-y-4">
              {basicFields.map((f) => renderField(f))}
            </div>
          ) : null}

          {/* Advanced Technical Settings Accordion */}
          {advancedFields.length > 0 ? (
            <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
              <button
                type="button"
                onClick={() => setIsAdvancedOpen((prev) => !prev)}
                className="flex w-full items-center justify-between p-4.5 text-left text-sm font-bold transition hover:bg-muted/30 focus:outline-none cursor-pointer"
              >
                <div className="flex items-center gap-2.5 text-foreground">
                  <SlidersHorizontal className="h-4 w-4 text-primary" />
                  <span>
                    {t("integrationsPage.advanced_settings") || "Parametri Avanzati"}
                  </span>
                  <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-bold text-muted-foreground">
                    {advancedFields.length}
                  </span>
                </div>
                <ChevronDown
                  className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${
                    isAdvancedOpen ? "rotate-180" : ""
                  }`}
                />
              </button>

              {isAdvancedOpen ? (
                <div className="border-t border-border p-4.5 space-y-4 bg-background/50">
                  {advancedFields.map((f) => renderField(f))}
                </div>
              ) : null}
            </div>
          ) : null}

          {/* Add Custom Field Button */}
          {!integration.has_oauth ? (
            <button
              type="button"
              onClick={addCustomField}
              className="flex w-full items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-border/80 p-4 text-xs font-bold text-muted-foreground hover:text-foreground hover:border-primary/50 hover:bg-muted/20 transition cursor-pointer"
            >
              <Plus className="h-4 w-4" aria-hidden />
              {t("integrationsPage.add_credential")}
            </button>
          ) : null}

          {/* Error Message */}
          {error ? (
            <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs font-semibold text-red-500">
              {error}
            </div>
          ) : null}
        </div>

        {/* Fixed Footer */}
        <div className="border-t border-border p-5 bg-muted/20 flex items-center justify-end gap-3 shrink-0 shadow-lg">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-border px-5 py-2.5 text-xs font-bold text-foreground hover:bg-muted transition cursor-pointer"
          >
            {oauthOnly && hasOAuthToken ? t("integrationsPage.close") : t("integrationsPage.cancel")}
          </button>
          {showSaveButton ? (
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving}
              className="rounded-xl bg-primary px-6 py-2.5 text-xs font-bold text-primary-foreground shadow-md shadow-primary/20 hover:bg-primary/90 transition cursor-pointer disabled:opacity-50"
            >
              {saving ? t("integrationsPage.saving") : t("integrationsPage.save")}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

