"use client";

import { Check, CheckCircle2, Clock, Globe, Lock, Plug, Settings, Sparkles, Unplug } from "lucide-react";

import type { Integration } from "@/components/integrations/types";
import { cn } from "@/lib/cn";
import { oauthProviderDisplayName } from "@/lib/integrations/oauthLabels";
import { useT } from "@/lib/i18n/use-t";

export function IntegrationCard({
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
  const t = useT();

  const hasOAuthToken = integration.credentials_hints.some(
    (h) => h.key === "OAUTH_TOKEN" && !h.is_expired,
  );
  const isConnected = integration.is_configured || hasOAuthToken;
  const isDisabled = integration.user_enabled === false;
  const providerLabel = oauthProviderDisplayName(integration);

  // Distinguiamo se richiede configurazione utente o se è attiva di sistema
  const requiresConfig =
    (integration.requires_user_credentials || integration.has_oauth) &&
    integration.credential_mode !== "none" &&
    !integration.org_managed;

  const oauthConnectLabel =
    integration.has_oauth && !isConnected
      ? t("integrationsPage.oauth_connect_service", { service: providerLabel })
      : connectLabel;

  return (
    <article
      className={cn(
        "group relative flex flex-col justify-between rounded-2xl border p-5 shadow-sm transition-all duration-200 hover:shadow-md",
        isDisabled && "opacity-60 bg-muted/20 border-border/50",
        !isDisabled && isConnected && requiresConfig
          ? "border-emerald-500/25 bg-gradient-to-b from-emerald-500/[0.04] to-card hover:border-emerald-500/40"
          : !isDisabled && !requiresConfig
            ? "border-sky-500/25 bg-gradient-to-b from-sky-500/[0.03] to-card hover:border-sky-500/40"
            : !isDisabled
              ? "border-amber-500/25 bg-gradient-to-b from-amber-500/[0.03] to-card hover:border-amber-500/40"
              : "border-border/70 bg-card",
      )}
    >
      <div>
        {/* Header con Icona, Titolo e Badge di Stato */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div
              className={cn(
                "flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-xl border transition-colors",
                isDisabled
                  ? "border-border/60 bg-muted/40 text-muted-foreground"
                  : isConnected && requiresConfig
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                    : !requiresConfig
                      ? "border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-400"
                      : "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400",
              )}
            >
              {integration.icon_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={integration.icon_url} alt="" className="h-full w-full object-cover" />
              ) : !requiresConfig ? (
                <Sparkles className="h-5 w-5" aria-hidden />
              ) : (
                <Plug className="h-5 w-5" aria-hidden />
              )}
            </div>

            <div className="min-w-0 flex-1">
              <h3 className="font-semibold text-foreground text-sm sm:text-base leading-tight truncate">
                {integration.display_name}
              </h3>
              {integration.category ? (
                <span className="text-[11px] font-medium text-muted-foreground capitalize">
                  {integration.category}
                </span>
              ) : null}
            </div>
          </div>

          {/* Badge di stato */}
          <div className="shrink-0">
            {isDisabled ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                {t("integrationsPage.badge_disabled")}
              </span>
            ) : !requiresConfig ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-sky-700 dark:text-sky-300 border border-sky-500/20">
                <Check className="h-3 w-3" />
                {t("integrationsPage.badge_system") || "Attivo"}
              </span>
            ) : isConnected ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-700 dark:text-emerald-300 border border-emerald-500/20">
                <CheckCircle2 className="h-3 w-3" />
                {t("integrationsPage.badge_connected")}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-amber-800 dark:text-amber-300 border border-amber-500/20">
                <Clock className="h-3 w-3" />
                {t("integrationsPage.badge_pending_short")}
              </span>
            )}
          </div>
        </div>

        {/* Descrizione (Mantenuta, chiara e ordinata) */}
        {integration.description ? (
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground line-clamp-3">
            {integration.description}
          </p>
        ) : null}

        {/* Informazioni di tipo / Gestione */}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          {integration.org_managed ? (
            <span className="inline-flex items-center gap-1 rounded-md bg-muted/50 px-2 py-0.5">
              <Globe className="h-3 w-3 opacity-70" />
              {orgManagedLabel}
            </span>
          ) : integration.has_oauth ? (
            <span className="inline-flex items-center gap-1 rounded-md bg-muted/50 px-2 py-0.5">
              <Lock className="h-3 w-3 opacity-70" />
              OAuth 2.0
            </span>
          ) : null}
        </div>
      </div>

      {/* Footer Azioni: Toggle Attivo + Pulsanti di configurazione */}
      <div className="mt-5 pt-3.5 border-t border-border/60 flex items-center justify-between gap-3">
        {/* Toggle On/Off per l'utente */}
        {integration.can_disable && onTogglePreference ? (
          <label className="flex cursor-pointer items-center gap-2 select-none group/toggle">
            <span className="relative inline-flex h-5 w-9 shrink-0 items-center">
              <input
                type="checkbox"
                className="peer sr-only"
                checked={integration.user_enabled !== false}
                onChange={(e) => onTogglePreference(integration.server_slug, e.target.checked)}
              />
              <span className="absolute inset-0 rounded-full bg-muted transition peer-checked:bg-primary" />
              <span className="absolute left-0.5 h-4 w-4 rounded-full bg-background shadow-sm transition peer-checked:translate-x-4" />
            </span>
            <span className="text-xs font-medium text-muted-foreground group-hover/toggle:text-foreground transition">
              {t("integrationsPage.toggle_active")}
            </span>
          </label>
        ) : (
          <div />
        )}

        {/* Pulsanti di azione se richiede credenziali ed è abilitato */}
        {requiresConfig && integration.user_enabled !== false ? (
          <div className="flex items-center gap-2">
            {integration.has_oauth && hasOAuthToken && onDisconnectOAuth ? (
              <button
                type="button"
                onClick={() => onDisconnectOAuth(integration.server_slug)}
                className="focus-ring inline-flex items-center gap-1.5 rounded-xl border border-destructive/25 bg-destructive/5 px-2.5 py-1.5 text-xs font-semibold text-destructive transition hover:bg-destructive/10 cursor-pointer"
                title={t("integrationsPage.disconnect")}
              >
                <Unplug className="h-3.5 w-3.5" aria-hidden />
                <span className="hidden sm:inline">{t("integrationsPage.disconnect")}</span>
              </button>
            ) : null}

            <button
              type="button"
              onClick={onConfigure}
              className={cn(
                "focus-ring inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition cursor-pointer shadow-sm",
                isConnected
                  ? "border border-border/80 bg-background/80 hover:bg-muted text-foreground"
                  : "bg-primary text-primary-foreground hover:bg-primary/90",
              )}
            >
              <Settings className="h-3.5 w-3.5" aria-hidden />
              {isConnected ? t("integrationsPage.edit") : oauthConnectLabel}
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
}

