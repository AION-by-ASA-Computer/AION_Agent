"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plug, Plus } from "lucide-react";
import { SecondaryPageLayout } from "@/components/layout/SecondaryPageLayout";
import { apiBase } from "@/lib/config";
import { jsonHeaders } from "@/lib/api/aion";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { useT } from "@/lib/i18n/use-t";

type CredentialField = {
  key: string;
  label: string;
  type: "text" | "password" | "oauth";
  required: boolean;
  description?: string;
};

type Integration = {
  server_slug: string;
  display_name: string;
  description?: string;
  icon_url?: string;
  category?: string;
  credential_mode?: "none" | "org_shared" | "per_user";
  org_managed?: boolean;
  requires_user_credentials: boolean;
  credential_schema: CredentialField[];
  has_oauth: boolean;
  is_remote_bridge?: boolean;
  remote_url?: string;
  oauth_provider?: string;
  oauth_authorization_server?: string;
  oauth_client_id?: string;
  oauth_scopes?: string[];
  is_configured: boolean;
  user_enabled?: boolean;
  can_disable?: boolean;
  credentials_hints: Array<{
    key: string;
    display_hint?: string;
    is_expired: boolean;
    updated_at?: string;
  }>;
};

export default function MyIntegrationsPage() {
  const t = useT();
  const userId = useStoredUserId();
  const token = useStoredToken();
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [configuringSlug, setConfiguringSlug] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [featureEnabled, setFeatureEnabled] = useState(true);
  const [featureHint, setFeatureHint] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setFetchError(null);
    try {
      const [statusRes, res] = await Promise.all([
        fetch(`${apiBase()}/v1/integrations/status`),
        fetch(`${apiBase()}/v1/integrations`, { headers: jsonHeaders(userId, token) }),
      ]);
      if (statusRes.ok) {
        const st = await statusRes.json();
        setFeatureEnabled(Boolean(st.credentials_feature_enabled));
        setFeatureHint(st.hint || null);
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || res.statusText);
      }
      const data = await res.json();
      setIntegrations(data.integrations || []);
      if (data.credentials_feature_enabled === false) {
        setFeatureEnabled(false);
      }
    } catch (e: unknown) {
      setFetchError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [userId, token]);

  async function togglePreference(slug: string, active: boolean) {
    const res = await fetch(`${apiBase()}/v1/integrations/${encodeURIComponent(slug)}/preference`, {
      method: "PATCH",
      headers: { ...jsonHeaders(userId, token), "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: active }),
    });
    if (!res.ok) throw new Error(await res.text());
    await load();
  }

  async function disconnectOAuth(slug: string) {
    try {
      const res = await fetch(
        `${apiBase()}/v1/integrations/credentials/${encodeURIComponent(slug)}/OAUTH_TOKEN`,
        { method: "DELETE", headers: jsonHeaders(userId, token) }
      );
      if (!res.ok) throw new Error(await res.text());
      await load();
    } catch (e: unknown) {
      setFetchError(e instanceof Error ? e.message : "Errore disconnessione OAuth");
    }
  }

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const oauthStatus = params.get("oauth_status");
    const oauthError = params.get("error");
    if (oauthStatus === "success") {
      window.history.replaceState({}, document.title, window.location.pathname);
      localStorage.removeItem("oauth_state");
      localStorage.removeItem("oauth_server_slug");
      localStorage.removeItem("oauth_redirect_uri");
      void load();
      return;
    }
    if (oauthStatus === "error") {
      window.history.replaceState({}, document.title, window.location.pathname);
      localStorage.removeItem("oauth_state");
      localStorage.removeItem("oauth_server_slug");
      localStorage.removeItem("oauth_redirect_uri");
      setFetchError(`OAuth error: ${oauthError || "Errore sconosciuto"}`);
      return;
    }

    const code = params.get("code");
    const state = params.get("state");
    
    if (code && state) {
      const savedState = localStorage.getItem("oauth_state");
      const serverSlug = localStorage.getItem("oauth_server_slug");
      const redirectUri = localStorage.getItem("oauth_redirect_uri");
      
      localStorage.removeItem("oauth_state");
      localStorage.removeItem("oauth_server_slug");
      localStorage.removeItem("oauth_redirect_uri");
      
      window.history.replaceState({}, document.title, window.location.pathname);
      
      if (!serverSlug) {
        setFetchError("OAuth callback error: Missing integration server identifier.");
        return;
      }
      
      if (state !== savedState) {
        setFetchError("OAuth callback security check failed: state mismatch.");
        return;
      }
      
      setLoading(true);
      fetch(`${apiBase()}/v1/integrations/oauth/callback`, {
        method: "POST",
        headers: jsonHeaders(userId, token),
        body: JSON.stringify({
          server_slug: serverSlug,
          code,
          state,
          redirect_uri: redirectUri,
        }),
      })
        .then(async (res) => {
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error((err as { detail?: string }).detail || "Failed to exchange OAuth token");
          }
          void load();
        })
        .catch((err: unknown) => {
          setFetchError(err instanceof Error ? err.message : "OAuth token exchange error");
          setLoading(false);
        });
    }
  }, [userId, token, load]);

  if (loading) {
    return (
      <div className="mx-auto max-w-3xl p-8 text-muted-foreground">
        {t("integrationsPage.loading")}
      </div>
    );
  }

  const configured = integrations.filter((i) => {
    const hasOAuthToken = i.credentials_hints.some(
      (h) => h.key === "OAUTH_TOKEN" && !h.is_expired
    );
    return i.is_configured || (i.has_oauth && hasOAuthToken);
  });
  const notConfigured = integrations.filter((i) => {
    const hasOAuthToken = i.credentials_hints.some(
      (h) => h.key === "OAUTH_TOKEN" && !h.is_expired
    );
    return !i.is_configured && !(i.has_oauth && hasOAuthToken);
  });

  return (
    <SecondaryPageLayout
      title={t("integrationsPage.title")}
      subtitle={t("integrationsPage.subtitle")}
      backLabel={t("integrationsPage.back_chat")}
    >
      {!featureEnabled && (
        <div className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-200">
          {featureHint || t("integrationsPage.feature_disabled")}
        </div>
      )}

      {fetchError && (
        <div className="mb-4 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {fetchError}
        </div>
      )}

      {integrations.length > 0 && (
        <div className="mb-6 flex flex-wrap gap-2">
          <span className="rounded-full bg-emerald-500/15 px-3 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-400">
            {configured.length} {t("integrationsPage.badge_configured")}
          </span>
          {notConfigured.length > 0 && (
            <span className="rounded-full bg-amber-500/15 px-3 py-1 text-xs font-medium text-amber-800 dark:text-amber-300">
              {notConfigured.length} {t("integrationsPage.badge_pending")}
            </span>
          )}
        </div>
      )}

      {configured.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("integrationsPage.section_configured")}
          </h2>
          <div className="space-y-2">
            {configured.map((intg) => (
              <IntegrationCard
                key={intg.server_slug}
                integration={intg}
                onConfigure={() => setConfiguringSlug(intg.server_slug)}
                connectLabel={t("integrationsPage.edit")}
                orgManagedLabel={t("integrationsPage.org_managed")}
                perUserHint={t("integrationsPage.per_user_hint")}
                onTogglePreference={(slug, active) => void togglePreference(slug, active)}
                onDisconnectOAuth={disconnectOAuth}
              />
            ))}
          </div>
        </div>
      )}

      {notConfigured.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("integrationsPage.section_pending")}
          </h2>
          <div className="space-y-2">
            {notConfigured.map((intg) => (
              <IntegrationCard
                key={intg.server_slug}
                integration={intg}
                onConfigure={() => setConfiguringSlug(intg.server_slug)}
                connectLabel={t("integrationsPage.connect")}
                orgManagedLabel={t("integrationsPage.org_managed")}
                perUserHint={t("integrationsPage.per_user_hint")}
                onTogglePreference={(slug, active) => void togglePreference(slug, active)}
                onDisconnectOAuth={disconnectOAuth}
              />
            ))}
          </div>
        </div>
      )}

      {integrations.length === 0 && !fetchError && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-16 text-center text-muted-foreground px-4">
          <Plug className="mb-3 h-10 w-10 opacity-40" aria-hidden />
          <p className="text-sm font-medium text-foreground">{t("integrationsPage.empty")}</p>
          <ul className="mt-4 text-left text-xs space-y-1 max-w-md">
            <li>{t("integrationsPage.checklist_hub")}</li>
            <li>{t("integrationsPage.checklist_per_user")}</li>
            <li>{t("integrationsPage.checklist_env")}</li>
            <li>{t("integrationsPage.checklist_login")}</li>
          </ul>
        </div>
      )}

      {configuringSlug && (
        <CredentialConfigDialog
          integration={integrations.find((i) => i.server_slug === configuringSlug)!}
          userId={userId}
          token={token}
          onClose={() => {
            setConfiguringSlug(null);
            void load();
          }}
        />
      )}
    </SecondaryPageLayout>
  );
}

function IntegrationCard({
  integration,
  onConfigure,
  connectLabel,
  orgManagedLabel,
  perUserHint,
  onTogglePreference,
  onDisconnectOAuth,
}: {
  integration: Integration;
  onConfigure: () => void;
  connectLabel: string;
  orgManagedLabel: string;
  perUserHint: string;
  onTogglePreference?: (slug: string, active: boolean) => void;
  onDisconnectOAuth?: (slug: string) => void;
}) {
  const hasOAuthToken = integration.credentials_hints.some(
    (h) => h.key === "OAUTH_TOKEN" && !h.is_expired
  );

  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4 ${
        integration.is_configured || hasOAuthToken
          ? "border-emerald-500/25 bg-emerald-500/5"
          : "border-border bg-card/30"
      }`}
    >
      <div className="flex min-w-0 items-center gap-3">
        {integration.icon_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={integration.icon_url} alt="" className="h-10 w-10 shrink-0 rounded-lg" />
        ) : (
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted text-lg font-semibold">
            {integration.display_name[0]?.toUpperCase() ?? "?"}
          </div>
        )}
        <div className="min-w-0">
          <div className="font-medium">{integration.display_name}</div>
          {integration.description && (
            <div className="text-xs text-muted-foreground">{integration.description}</div>
          )}
          {integration.org_managed && (
            <p className="mt-1 text-xs text-muted-foreground">{orgManagedLabel}</p>
          )}
          {integration.credential_mode === "per_user" && !integration.org_managed && (
            <p className="mt-1 text-xs text-muted-foreground">{perUserHint}</p>
          )}
          {(integration.is_configured || hasOAuthToken) && (
            <div className="mt-1 flex flex-wrap gap-1 items-center">
              {integration.has_oauth && hasOAuthToken && (
                <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:text-emerald-300">
                  ✓ OAuth connesso
                </span>
              )}
              {integration.has_oauth && !hasOAuthToken && !integration.is_configured && (
                <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-800 dark:text-amber-300">
                  OAuth richiesto
                </span>
              )}
              {integration.credentials_hints
                .filter((h) => h.key !== "OAUTH_TOKEN")
                .map((h) => (
                  <span
                    key={h.key}
                    className={`rounded-full px-2 py-0.5 text-xs ${
                      h.is_expired
                        ? "bg-destructive/15 text-destructive"
                        : "bg-emerald-500/15 text-emerald-800 dark:text-emerald-300"
                    }`}
                  >
                    {h.display_hint || h.key}
                    {h.is_expired ? " · expired" : ""}
                  </span>
                ))}
            </div>
          )}
        </div>
      </div>
      {integration.can_disable && onTogglePreference && (
        <label className="flex items-center gap-2 text-xs text-muted-foreground shrink-0">
          <input
            type="checkbox"
            checked={integration.user_enabled !== false}
            onChange={(e) => onTogglePreference(integration.server_slug, e.target.checked)}
          />
          Attiva
        </label>
      )}
      {!integration.org_managed && integration.credential_mode !== "none" && integration.user_enabled !== false && (
        <div className="flex items-center gap-2">
          {integration.has_oauth && hasOAuthToken && onDisconnectOAuth && (
            <button
              type="button"
              onClick={() => onDisconnectOAuth(integration.server_slug)}
              className="focus-ring shrink-0 rounded-lg border border-destructive/30 px-3 py-2 text-sm font-medium text-destructive hover:bg-destructive/10 transition-colors"
            >
              Disconnetti
            </button>
          )}
          <button
            type="button"
            onClick={onConfigure}
            className={`focus-ring shrink-0 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              integration.is_configured || hasOAuthToken
                ? "border border-border hover:bg-muted"
                : "bg-primary text-primary-foreground hover:bg-primary/90"
            }`}
          >
            {connectLabel}
          </button>
        </div>
      )}
    </div>
  );
}

function CredentialConfigDialog({
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

  function getOAuthButtonText() {
    const provider = integration.oauth_provider || "oauth2";
    if (provider.toLowerCase() === "google") {
      return "Accedi con Google";
    }
    if (provider.toLowerCase() === "github") {
      return "Accedi con GitHub";
    }
    if (provider.toLowerCase() === "microsoft") {
      return "Accedi con Microsoft";
    }
    if (provider.toLowerCase() === "auth0") {
      return "Accedi con Auth0";
    }
    return `Accedi con ${provider.charAt(0).toUpperCase() + provider.slice(1)}`;
  }

  const hasOAuthToken = useMemo(() => {
    return integration.credentials_hints.some(
      (h) => h.key === "OAUTH_TOKEN" && !h.is_expired
    );
  }, [integration.credentials_hints]);

  async function handleOAuthLogin() {
    const redirectUri = `${apiBase()}/v1/integrations/oauth/callback`;
    try {
      const res = await fetch(
        `${apiBase()}/v1/integrations/oauth/start?server_slug=${encodeURIComponent(integration.server_slug)}&redirect_uri=${encodeURIComponent(redirectUri)}`,
        { headers: jsonHeaders(userId, token) }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setError((err as { detail?: string }).detail || "Errore avvio OAuth");
        return;
      }
      const data = await res.json() as { authorization_url: string; state: string };
      localStorage.setItem("oauth_state", data.state);
      localStorage.setItem("oauth_server_slug", integration.server_slug);
      window.location.href = data.authorization_url;
    } catch (e) {
      setError("Errore di rete durante l'avvio OAuth.");
    }
  }

  const placeholders: Record<string, string> = {};
  integration.credentials_hints.forEach((h) => {
    placeholders[h.key] = h.display_hint
      ? `(${h.display_hint})`
      : "(saved)";
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
      (f) => f.required && !values[f.key]?.trim() && !placeholders[f.key]
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-border bg-background shadow-xl">
        <div className="p-6">
          <div className="mb-4 flex items-center gap-3">
            {integration.icon_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={integration.icon_url} alt="" className="h-10 w-10 rounded-lg" />
            ) : (
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted font-semibold">
                {integration.display_name[0]?.toUpperCase() ?? "?"}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold">
                {integration.display_name}
              </h2>
              {integration.description && (
                <p className="text-xs text-muted-foreground">{integration.description}</p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="focus-ring text-muted-foreground hover:text-foreground"
              aria-label={t("integrationsPage.cancel")}
            >
              ×
            </button>
          </div>

          <p className="mb-4 rounded-lg border border-border bg-muted/40 p-3 text-xs text-muted-foreground">
            {t("integrationsPage.security")}
          </p>

          <div className="space-y-4">
            {integration.has_oauth && (
              <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 text-center">
                <h3 className="mb-2 text-sm font-semibold">
                  Autenticazione OAuth2
                </h3>
                {hasOAuthToken ? (
                  <>
                    <p className="mb-4 text-xs text-emerald-600 dark:text-emerald-400 font-medium">
                      ✓ OAuth connesso
                    </p>
                    <button
                      type="button"
                      onClick={handleOAuthLogin}
                      className="focus-ring flex w-full items-center justify-center gap-2 rounded-lg border border-border bg-card px-4 py-2 text-sm font-medium hover:bg-muted transition-all"
                    >
                      <Plug className="h-4 w-4" />
                      Riconnetti account
                    </button>
                  </>
                ) : (
                  <>
                    <p className="mb-4 text-xs text-muted-foreground">
                      Connetti questa integrazione accedendo in modo sicuro con il tuo account.
                    </p>
                    <button
                      type="button"
                      onClick={handleOAuthLogin}
                      className="focus-ring flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-all shadow-sm"
                    >
                      <Plug className="h-4 w-4" />
                      {getOAuthButtonText()}
                    </button>
                  </>
                )}
              </div>
            )}

            {formFields.length > 0 && formFields.map((field) => {
              const custom = customFields.find((c) => normalizeKey(c.key) === field.key);
              const isCustom = Boolean(custom);
                            return (
                <div key={isCustom ? custom!.id : field.key}>
                  <label className="mb-1 block text-sm font-medium">
                    {isCustom ? custom!.label || field.label : field.label}
                    {field.required && <span className="ml-1 text-destructive">*</span>}
                    {isCustom && (
                      <span className="ml-2 text-xs font-normal text-muted-foreground">
                        ({t("integrationsPage.custom_field")})
                      </span>
                    )}
                  </label>
                  {field.description && (
                    <p className="mb-1 text-xs text-muted-foreground">{field.description}</p>
                  )}
                  {isCustom && custom && (
                    <div className="mb-2 grid grid-cols-2 gap-2">
                      <input
                        className="focus-ring rounded-lg border border-input bg-background px-2 py-1.5 font-mono text-xs"
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
                        className="focus-ring rounded-lg border border-input bg-background px-2 py-1.5 text-xs"
                        value={custom.label}
                        onChange={(e) => {
                          setCustomFields((prev) =>
                            prev.map((c) => (c.id === custom.id ? { ...c, label: e.target.value } : c)),
                          );
                        }}
                        placeholder={t("integrationsPage.field_label")}
                      />
                    </div>
                  )}
                  {field.type === "oauth" ? (
                    <div className="space-y-1">
                      <p className="text-xs text-muted-foreground">
                        {t("integrationsPage.pat_hint")}
                      </p>
                      <input
                        type="password"
                        value={values[field.key] || ""}
                        onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
                        placeholder={placeholders[field.key] || t("integrationsPage.pat_placeholder")}
                        className="focus-ring w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                      />
                    </div>
                  ) : (
                    <input
                      type={field.type === "password" ? "password" : "text"}
                      value={values[field.key] || ""}
                      onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
                      placeholder={placeholders[field.key] || field.label}
                      className="focus-ring w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                    />
                  )}
                </div>
              );
            })}
            
            {!integration.has_oauth && (
              <button
                type="button"
                onClick={addCustomField}
                className="focus-ring flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-border py-2.5 text-sm text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              >
                <Plus className="h-4 w-4" />
                {t("integrationsPage.add_credential")}
              </button>
            )}
          </div>

          {error && (
            <div className="mt-4 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          <div className="mt-6 flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="focus-ring rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted"
            >
              {t("integrationsPage.cancel")}
            </button>
            {(!integration.has_oauth || formFields.length > 0) && (
              <button
                type="button"
                onClick={() => void save()}
                disabled={saving}
                className="focus-ring rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
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
