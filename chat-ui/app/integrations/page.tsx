"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plug } from "lucide-react";

import { CredentialConfigDialog } from "@/components/integrations/CredentialConfigDialog";
import { IntegrationCard } from "@/components/integrations/IntegrationCard";
import { IntegrationStatsBar } from "@/components/integrations/IntegrationStatsBar";
import { IntegrationsEmptyState } from "@/components/integrations/IntegrationsEmptyState";
import type { Integration } from "@/components/integrations/types";
import { SecondaryPageLayout } from "@/components/layout/SecondaryPageLayout";
import { apiBase } from "@/lib/config";
import { jsonHeaders } from "@/lib/api/aion";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { useT } from "@/lib/i18n/use-t";

function isIntegrationConnected(integration: Integration) {
  const hasOAuthToken = integration.credentials_hints.some(
    (h) => h.key === "OAUTH_TOKEN" && !h.is_expired,
  );
  return integration.is_configured || (integration.has_oauth && hasOAuthToken);
}

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
        { method: "DELETE", headers: jsonHeaders(userId, token) },
      );
      if (!res.ok) throw new Error(await res.text());
      await load();
    } catch (e: unknown) {
      setFetchError(e instanceof Error ? e.message : t("integrationsPage.disconnect_error"));
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
      setFetchError(`OAuth error: ${oauthError || t("integrationsPage.oauth_unknown_error")}`);
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
        setFetchError(t("integrationsPage.oauth_callback_missing_slug"));
        return;
      }

      if (state !== savedState) {
        setFetchError(t("integrationsPage.oauth_callback_state_mismatch"));
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
            throw new Error((err as { detail?: string }).detail || t("integrationsPage.oauth_exchange_error"));
          }
          void load();
        })
        .catch((err: unknown) => {
          setFetchError(err instanceof Error ? err.message : t("integrationsPage.oauth_exchange_error"));
          setLoading(false);
        });
    }
  }, [userId, token, load, t]);

  const { configured, notConfigured } = useMemo(() => {
    const connected: Integration[] = [];
    const pending: Integration[] = [];
    for (const intg of integrations) {
      if (isIntegrationConnected(intg)) connected.push(intg);
      else pending.push(intg);
    }
    return { configured: connected, notConfigured: pending };
  }, [integrations]);

  const configuringIntegration = configuringSlug
    ? integrations.find((i) => i.server_slug === configuringSlug)
    : null;

  if (loading) {
    return (
      <div className="mx-auto max-w-3xl p-8 text-muted-foreground">
        {t("integrationsPage.loading")}
      </div>
    );
  }

  return (
    <SecondaryPageLayout
      title={t("integrationsPage.title")}
      subtitle={t("integrationsPage.subtitle")}
      backLabel={t("integrationsPage.back_chat")}
      headerIcon={<Plug className="h-5 w-5" aria-hidden />}
    >
      {!featureEnabled ? (
        <div className="mb-4 rounded-2xl border border-amber-500/35 bg-amber-500/10 px-4 py-3 text-sm text-amber-900 dark:text-amber-200">
          {featureHint || t("integrationsPage.feature_disabled")}
        </div>
      ) : null}

      {fetchError ? (
        <div className="mb-4 rounded-2xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {fetchError}
        </div>
      ) : null}

      <IntegrationStatsBar
        total={integrations.length}
        configured={configured.length}
        pending={notConfigured.length}
      />

      {configured.length > 0 ? (
        <section className="mb-8">
          <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
            {t("integrationsPage.section_configured")}
          </h2>
          <div className="space-y-3">
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
        </section>
      ) : null}

      {notConfigured.length > 0 ? (
        <section className="mb-8">
          <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
            {t("integrationsPage.section_pending")}
          </h2>
          <div className="space-y-3">
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
        </section>
      ) : null}

      {integrations.length === 0 && !fetchError ? <IntegrationsEmptyState /> : null}

      {configuringIntegration && userId ? (
        <CredentialConfigDialog
          integration={configuringIntegration}
          userId={userId}
          token={token}
          onClose={() => {
            setConfiguringSlug(null);
            void load();
          }}
        />
      ) : null}
    </SecondaryPageLayout>
  );
}
