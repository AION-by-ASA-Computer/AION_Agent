"use client";

import { Plug, Unplug } from "lucide-react";

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
  const oauthConnectLabel =
    integration.has_oauth && !isConnected
      ? t("integrationsPage.oauth_connect_service", { service: providerLabel })
      : connectLabel;

  return (
    <article
      className={cn(
        "overflow-hidden rounded-2xl border shadow-sm backdrop-blur-sm transition hover:shadow-md",
        isDisabled && "opacity-60",
        isConnected && !isDisabled
          ? "border-emerald-500/20 bg-gradient-to-br from-emerald-500/6 to-card/40"
          : "border-border/70 bg-card/35",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-4 p-4 sm:p-5">
        <div className="flex min-w-0 flex-1 items-start gap-3.5">
          <div
            className={cn(
              "flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-2xl border",
              isConnected && !isDisabled
                ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "border-border/60 bg-muted/50 text-muted-foreground",
            )}
          >
            {integration.icon_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={integration.icon_url} alt="" className="h-full w-full object-cover" />
            ) : (
              <Plug className="h-5 w-5" aria-hidden />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold text-foreground">{integration.display_name}</h3>
              {isDisabled ? (
                <span className="rounded-full bg-muted px-2 py-0.5 text-[0.714em] font-bold uppercase text-muted-foreground">
                  {t("integrationsPage.badge_disabled")}
                </span>
              ) : (
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[0.714em] font-bold uppercase",
                    isConnected
                      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                      : "bg-amber-500/15 text-amber-800 dark:text-amber-300",
                  )}
                >
                  {isConnected
                    ? t("integrationsPage.badge_connected")
                    : t("integrationsPage.badge_pending_short")}
                </span>
              )}
            </div>
            {integration.description ? (
              <p className="mt-0.5 text-sm text-muted-foreground">{integration.description}</p>
            ) : null}
            {integration.org_managed ? (
              <p className="mt-2 text-[0.786em] text-muted-foreground">{orgManagedLabel}</p>
            ) : null}
            {integration.credential_mode === "per_user" && !integration.org_managed ? (
              <p className="mt-2 text-[0.786em] text-muted-foreground">
                {isDisabled ? t("integrationsPage.disabled_hint") : perUserHint}
              </p>
            ) : null}
            {isConnected && !isDisabled ? (
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {integration.has_oauth && hasOAuthToken ? (
                  <span className="rounded-md bg-emerald-500/15 px-2 py-0.5 text-[0.714em] font-semibold text-emerald-800 dark:text-emerald-300">
                    {t("integrationsPage.oauth_connected_service", { service: providerLabel })}
                  </span>
                ) : null}
                {integration.has_oauth && !hasOAuthToken && !integration.is_configured ? (
                  <span className="rounded-md bg-amber-500/15 px-2 py-0.5 text-[0.714em] font-semibold text-amber-800 dark:text-amber-300">
                    {t("integrationsPage.oauth_required_service", { service: providerLabel })}
                  </span>
                ) : null}
                {integration.credentials_hints
                  .filter((h) => h.key !== "OAUTH_TOKEN" && h.key !== "OAUTH_REFRESH_TOKEN")
                  .map((h) => (
                    <span
                      key={h.key}
                      className={cn(
                        "rounded-md px-2 py-0.5 text-[0.714em] font-medium",
                        h.is_expired
                          ? "bg-destructive/15 text-destructive"
                          : "bg-emerald-500/15 text-emerald-800 dark:text-emerald-300",
                      )}
                    >
                      {h.display_hint || h.key}
                      {h.is_expired ? ` · ${t("integrationsPage.credential_expired")}` : ""}
                    </span>
                  ))}
              </div>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2 sm:flex-row sm:items-center">
          {integration.can_disable && onTogglePreference ? (
            <label className="flex cursor-pointer items-center gap-2.5 rounded-xl border border-border/70 bg-background/60 px-3 py-2 text-xs">
              <span className="text-muted-foreground">{t("integrationsPage.toggle_active")}</span>
              <span className="relative inline-flex h-5 w-9 shrink-0 items-center">
                <input
                  type="checkbox"
                  className="peer sr-only"
                  checked={integration.user_enabled !== false}
                  onChange={(e) => onTogglePreference(integration.server_slug, e.target.checked)}
                />
                <span className="absolute inset-0 rounded-full bg-muted transition peer-checked:bg-primary" />
                <span className="absolute left-0.5 h-4 w-4 rounded-full bg-background shadow transition peer-checked:translate-x-4" />
              </span>
            </label>
          ) : null}
          {!integration.org_managed &&
          integration.credential_mode !== "none" &&
          integration.user_enabled !== false ? (
            <div className="flex flex-wrap items-center justify-end gap-2">
              {integration.has_oauth && hasOAuthToken && onDisconnectOAuth ? (
                <button
                  type="button"
                  onClick={() => onDisconnectOAuth(integration.server_slug)}
                  className="focus-ring inline-flex items-center gap-1.5 rounded-xl border border-destructive/25 bg-destructive/5 px-3 py-2 text-xs font-semibold text-destructive transition hover:bg-destructive/10"
                >
                  <Unplug className="h-3.5 w-3.5" aria-hidden />
                  {t("integrationsPage.disconnect")}
                </button>
              ) : null}
              <button
                type="button"
                onClick={onConfigure}
                className={cn(
                  "focus-ring rounded-xl px-3.5 py-2 text-xs font-semibold transition",
                  isConnected
                    ? "border border-border/70 bg-background/60 hover:bg-muted"
                    : "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90",
                )}
              >
                {oauthConnectLabel}
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </article>
  );
}
