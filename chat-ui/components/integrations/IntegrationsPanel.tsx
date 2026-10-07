"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { CheckCircle2, Clock, Filter, Plug, Search, Sparkles, XCircle } from "lucide-react";

import { CredentialConfigDialog } from "@/components/integrations/CredentialConfigDialog";
import { IntegrationCard } from "@/components/integrations/IntegrationCard";
import { IntegrationsEmptyState } from "@/components/integrations/IntegrationsEmptyState";
import type { Integration } from "@/components/integrations/types";
import { ShellSectionHeader } from "@/components/layout/ShellSectionHeader";
import { apiBase } from "@/lib/config";
import { jsonHeaders } from "@/lib/api/aion";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { useShellActions } from "@/lib/shell/shell-context";
import { useT } from "@/lib/i18n/use-t";
import { cn } from "@/lib/cn";

function isIntegrationConnected(integration: Integration) {
  const hasOAuthToken = integration.credentials_hints.some(
    (h) => h.key === "OAUTH_TOKEN" && !h.is_expired,
  );
  return integration.is_configured || (integration.has_oauth && hasOAuthToken);
}

function requiresUserConfiguration(integration: Integration) {
  return (
    (integration.requires_user_credentials || integration.has_oauth) &&
    integration.credential_mode !== "none" &&
    !integration.org_managed
  );
}

type CategoryTab = "all" | "configured" | "pending" | "system" | "disabled";

export function IntegrationsPanel() {
  const t = useT();
  const { setHeader, setDock, setDockOpen, clearChrome } = useShellActions();
  const userId = useStoredUserId();
  const token = useStoredToken();
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [configuringSlug, setConfiguringSlug] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [featureEnabled, setFeatureEnabled] = useState(true);
  const [featureHint, setFeatureHint] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTab, setSelectedTab] = useState<CategoryTab>("all");
  const [adminSetupPending, setAdminSetupPending] = useState<Array<{ server_slug: string; display_name: string }>>(
    [],
  );

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
      setAdminSetupPending(
        Array.isArray(data.admin_setup_pending) ? data.admin_setup_pending : [],
      );
      if (data.credentials_feature_enabled === false) {
        setFeatureEnabled(false);
      }
    } catch (e: unknown) {
      setFetchError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [userId, token]);

  useLayoutEffect(() => {
    setHeader(
      <ShellSectionHeader
        title={t("integrationsPage.title")}
        subtitle={t("integrationsPage.subtitle")}
        icon={<Plug className="h-5 w-5" aria-hidden />}
      />,
    );
    setDock(null);
    setDockOpen(false);
  }, [setHeader, setDock, setDockOpen, t]);

  useLayoutEffect(() => {
    return () => clearChrome();
  }, [clearChrome]);

  async function togglePreference(slug: string, active: boolean) {
    try {
      const res = await fetch(`${apiBase()}/v1/integrations/${encodeURIComponent(slug)}/preference`, {
        method: "PATCH",
        headers: { ...jsonHeaders(userId, token), "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: active }),
      });
      if (!res.ok) throw new Error(await res.text());
      await load();
    } catch (e: unknown) {
      setFetchError(e instanceof Error ? e.message : t("integrationsPage.toggle_error"));
    }
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

  // Suddivisione nelle 4 categorie distinte:
  // 1. configured: richiede credenziali ed è configurata dall'utente
  // 2. pending: richiede credenziali e NON è ancora configurata
  // 3. systemActive: attiva di default/sistema senza bisogno di credenziali dall'utente
  // 4. disabled: disattivata dall'utente
  const { configured, pending, systemActive, disabled } = useMemo(() => {
    const confList: Integration[] = [];
    const pendList: Integration[] = [];
    const sysList: Integration[] = [];
    const disList: Integration[] = [];

    for (const intg of integrations) {
      if (intg.user_enabled === false) {
        disList.push(intg);
        continue;
      }

      const reqUser = requiresUserConfiguration(intg);

      if (reqUser) {
        if (isIntegrationConnected(intg)) {
          confList.push(intg);
        } else {
          pendList.push(intg);
        }
      } else {
        // Attivo di sistema / senza configurazione richiesta
        sysList.push(intg);
      }
    }

    return {
      configured: confList,
      pending: pendList,
      systemActive: sysList,
      disabled: disList,
    };
  }, [integrations]);

  // Filtro di ricerca per testo
  const filterBySearch = useCallback(
    (list: Integration[]) => {
      const q = searchQuery.trim().toLowerCase();
      if (!q) return list;
      return list.filter(
        (i) =>
          i.display_name.toLowerCase().includes(q) ||
          (i.description && i.description.toLowerCase().includes(q)) ||
          i.server_slug.toLowerCase().includes(q),
      );
    },
    [searchQuery],
  );

  const filteredConfigured = useMemo(() => filterBySearch(configured), [configured, filterBySearch]);
  const filteredPending = useMemo(() => filterBySearch(pending), [pending, filterBySearch]);
  const filteredSystem = useMemo(() => filterBySearch(systemActive), [systemActive, filterBySearch]);
  const filteredDisabled = useMemo(() => filterBySearch(disabled), [disabled, filterBySearch]);

  const totalFilteredCount =
    (selectedTab === "all" || selectedTab === "configured" ? filteredConfigured.length : 0) +
    (selectedTab === "all" || selectedTab === "pending" ? filteredPending.length : 0) +
    (selectedTab === "all" || selectedTab === "system" ? filteredSystem.length : 0) +
    (selectedTab === "all" || selectedTab === "disabled" ? filteredDisabled.length : 0);

  const configuringIntegration = configuringSlug
    ? integrations.find((i) => i.server_slug === configuringSlug)
    : null;

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-muted-foreground">
        {t("integrationsPage.loading")}
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
        {/* Banner stato funzionalità */}
        {!featureEnabled ? (
          <div className="rounded-2xl border border-amber-500/35 bg-amber-500/10 px-4 py-3 text-sm text-amber-900 dark:text-amber-200">
            {featureHint || t("integrationsPage.feature_disabled")}
          </div>
        ) : null}

        {fetchError ? (
          <div className="rounded-2xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {fetchError}
          </div>
        ) : null}

        {adminSetupPending.length > 0 ? (
          <div className="rounded-2xl border border-border/70 bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
            {t("integrationsPage.admin_setup_required")}
          </div>
        ) : null}

        {/* Barra Filtri: Ricerca e Tab Categorie */}
        {integrations.length > 0 ? (
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 pb-2 border-b border-border/60">
            {/* Tab di selezione categoria */}
            <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-2xl bg-muted/40 border border-border/60">
              <button
                type="button"
                onClick={() => setSelectedTab("all")}
                className={cn(
                  "focus-ring inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition cursor-pointer",
                  selectedTab === "all"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <span>{t("integrationsPage.tab_all") || "Tutti"}</span>
                <span className="rounded-full bg-muted px-1.5 py-0.2 text-[10px] font-bold">
                  {integrations.length}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setSelectedTab("configured")}
                className={cn(
                  "focus-ring inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition cursor-pointer",
                  selectedTab === "configured"
                    ? "bg-background text-emerald-600 dark:text-emerald-400 shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                <span>{t("integrationsPage.tab_configured") || "Configurati"}</span>
                <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.2 text-[10px] font-bold text-emerald-700 dark:text-emerald-300">
                  {configured.length}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setSelectedTab("pending")}
                className={cn(
                  "focus-ring inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition cursor-pointer",
                  selectedTab === "pending"
                    ? "bg-background text-amber-600 dark:text-amber-400 shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Clock className="h-3.5 w-3.5 text-amber-500" />
                <span>{t("integrationsPage.tab_pending") || "Da configurare"}</span>
                <span className="rounded-full bg-amber-500/15 px-1.5 py-0.2 text-[10px] font-bold text-amber-800 dark:text-amber-300">
                  {pending.length}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setSelectedTab("system")}
                className={cn(
                  "focus-ring inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition cursor-pointer",
                  selectedTab === "system"
                    ? "bg-background text-sky-600 dark:text-sky-400 shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Sparkles className="h-3.5 w-3.5 text-sky-500" />
                <span>{t("integrationsPage.tab_system") || "Attivi di sistema"}</span>
                <span className="rounded-full bg-sky-500/15 px-1.5 py-0.2 text-[10px] font-bold text-sky-800 dark:text-sky-300">
                  {systemActive.length}
                </span>
              </button>

              {disabled.length > 0 ? (
                <button
                  type="button"
                  onClick={() => setSelectedTab("disabled")}
                  className={cn(
                    "focus-ring inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition cursor-pointer",
                    selectedTab === "disabled"
                      ? "bg-background text-muted-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <XCircle className="h-3.5 w-3.5" />
                  <span>{t("integrationsPage.tab_disabled") || "Disattivati"}</span>
                  <span className="rounded-full bg-muted px-1.5 py-0.2 text-[10px] font-bold">
                    {disabled.length}
                  </span>
                </button>
              ) : null}
            </div>

            {/* Input di Ricerca */}
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t("integrationsPage.search_placeholder") || "Cerca integrazione…"}
                className="w-full rounded-xl border border-border/80 bg-background pl-9 pr-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition"
              />
            </div>
          </div>
        ) : null}

        {/* Nessun risultato dalla ricerca */}
        {integrations.length > 0 && totalFilteredCount === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground rounded-2xl border border-dashed border-border/80 bg-card/40">
            {t("integrationsPage.filter_no_results") || "Nessuna integrazione trovata con questo filtro."}
          </div>
        ) : null}

        {/* Sezione 1: Integrazioni Configurate */}
        {(selectedTab === "all" || selectedTab === "configured") && filteredConfigured.length > 0 ? (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  {t("integrationsPage.section_configured")}
                </h2>
                <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold text-emerald-700 dark:text-emerald-300">
                  {filteredConfigured.length}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {filteredConfigured.map((intg) => (
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

        {/* Sezione 2: Da configurare */}
        {(selectedTab === "all" || selectedTab === "pending") && filteredPending.length > 0 ? (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-amber-500" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  {t("integrationsPage.section_pending")}
                </h2>
                <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold text-amber-800 dark:text-amber-300">
                  {filteredPending.length}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {filteredPending.map((intg) => (
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

        {/* Sezione 3: Attive di sistema / Pronte all'uso senza configurazione */}
        {(selectedTab === "all" || selectedTab === "system") && filteredSystem.length > 0 ? (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-sky-500" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  {t("integrationsPage.section_system") || "Attive di sistema"}
                </h2>
                <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-[10px] font-bold text-sky-800 dark:text-sky-300">
                  {filteredSystem.length}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {filteredSystem.map((intg) => (
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

        {/* Sezione 4: Disattivate dall'utente */}
        {(selectedTab === "all" || selectedTab === "disabled") && filteredDisabled.length > 0 ? (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <XCircle className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  {t("integrationsPage.section_disabled")}
                </h2>
                <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-bold text-muted-foreground">
                  {filteredDisabled.length}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {filteredDisabled.map((intg) => (
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

        {/* Modale Configurazione Credenziali */}
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
      </div>
    </div>
  );
}

