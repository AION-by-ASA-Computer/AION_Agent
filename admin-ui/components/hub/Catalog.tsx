"use client";

import { Box, Download, ExternalLink, Globe, Loader2, Search, ShieldCheck, Sparkles } from "lucide-react";
import { cn } from "@/lib/cn";
import { Select } from "@/components/ui/Select";
import { inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";
import { MCP_CATEGORIES, type McpCategory } from "@/lib/mcpCategories";
import type { Hub } from "@/components/hub/useHub";

/* eslint-disable @typescript-eslint/no-explicit-any */

const SOURCES = ["Smithery", "Glama.ai", "Google Cloud", "Claude Community", "GitHub", "Awesome List"];

function docUrlFor(item: any): string | undefined {
  if (item.url || item.homepage) return item.url || item.homepage;
  const id: string = item.id || "";
  if (id.startsWith("github:")) return `https://github.com/${id.replace("github:", "")}`;
  if (id.startsWith("glama:")) return `https://github.com/${id.replace("glama:", "")}`;
  if (id.startsWith("smithery:")) return `https://smithery.ai/server/${id.replace("smithery:", "")}`;
  if (item.qualified_name) {
    return item.qualified_name.includes("/") && !item.qualified_name.startsWith("@")
      ? `https://github.com/${item.qualified_name}`
      : `https://smithery.ai/server/${item.qualified_name}`;
  }
  if (item.name?.includes("/")) return `https://github.com/${item.name}`;
  return undefined;
}

function Tag({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "warning" | "success" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium",
        tone === "muted" && "bg-secondary text-muted-foreground",
        tone === "success" && "bg-success/12 text-success",
        tone === "warning" && "bg-warning/14 text-warning",
      )}
    >
      {children}
    </span>
  );
}

function CardShell({
  icon,
  title,
  href,
  subtitle,
  description,
  tags,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  href?: string;
  subtitle?: string;
  description: string;
  tags: React.ReactNode;
  action: React.ReactNode;
}) {
  return (
    <li className="flex flex-col rounded-2xl border border-border/70 bg-card p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-secondary text-muted-foreground" aria-hidden>
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          {href ? (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="focus-ring group inline-flex max-w-full items-center gap-1.5 rounded-md text-sm font-semibold hover:underline"
            >
              <span className="truncate">{title}</span>
              <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
            </a>
          ) : (
            <div className="truncate text-sm font-semibold">{title}</div>
          )}
          {subtitle && <div className="truncate font-mono text-[11.5px] text-muted-foreground">{subtitle}</div>}
        </div>
      </div>
      <p className="mt-3 line-clamp-2 min-h-[2.6rem] text-[13px] leading-relaxed text-muted-foreground">{description}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border/50 pt-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">{tags}</div>
        {action}
      </div>
    </li>
  );
}

export function Catalog({ hub }: { hub: Hub }) {
  const { t } = hub;
  const k = "admin_hub.catalog";
  const busyInstall = hub.installingId !== null || hub.marketLoading;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            void hub.runMarketSearch(hub.marketQuery);
          }}
          role="search"
        >
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <input
              type="search"
              value={hub.marketQuery}
              onChange={(e) => hub.setMarketQuery(e.target.value)}
              placeholder={t(`${k}.search`)}
              aria-label={t(`${k}.search`)}
              className={cn(inputCls, "bg-card pl-10")}
            />
          </div>
          <div className="sm:w-52">
            <Select
              className="bg-card"
              value={hub.marketSource}
              onChange={hub.setMarketSource}
              aria-label={t(`${k}.source`)}
              options={[{ value: "all", label: t(`${k}.source_all`) }, ...SOURCES.map((x) => ({ value: x, label: x }))]}
            />
          </div>
          <button type="submit" className={solidBtn + " h-[2.625rem] justify-center"} disabled={hub.marketLoading || !hub.marketQuery.trim()}>
            {hub.marketLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Search className="h-3.5 w-3.5" aria-hidden />}
            {t(`${k}.search_btn`)}
          </button>
        </form>

        <div role="group" aria-label={t(`${k}.categories`)} className="no-scrollbar -mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
          {MCP_CATEGORIES.map((c) => {
            const active = hub.marketCategory === c.id;
            return (
              <button
                key={c.id}
                type="button"
                aria-pressed={active}
                onClick={() => hub.setMarketCategory(c.id as McpCategory)}
                className={cn(
                  "focus-ring shrink-0 rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors",
                  active
                    ? "border-foreground bg-foreground text-background"
                    : "border-border bg-card text-muted-foreground hover:border-foreground/30 hover:text-foreground",
                )}
              >
                {t(`admin_hub.category.${c.id}`)}
              </button>
            );
          })}
        </div>
      </div>

      {(hub.marketCategory === "all" || hub.marketCategory === "official" || hub.featuredShown.length > 0) && hub.featuredShown.length > 0 && (
        <section aria-labelledby="hub-official">
          <div className="mb-3 flex items-baseline gap-3 px-1">
            <h2 id="hub-official" className="text-lg font-semibold tracking-[-0.015em]">
              {t(`${k}.official_title`)}
            </h2>
            <span className="text-sm tabular-nums text-muted-foreground">{hub.featuredShown.length}</span>
          </div>
          <p className="mb-4 px-1 text-sm text-muted-foreground">{t(`${k}.official_hint`)}</p>
          <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {hub.featuredShown.map((c: any) => {
              const id = String(c.id || "");
              const doc = String(c.official_doc_url || c.remote_url || c.homepage || "").trim() || undefined;
              const installing = hub.installingId === `catalog:${id}`;
              return (
                <CardShell
                  key={id}
                  icon={<ShieldCheck className="h-[18px] w-[18px]" />}
                  title={String(c.title || id)}
                  href={doc}
                  subtitle={id}
                  description={String(c.description || "").trim() || String(c.remote_url || "")}
                  tags={
                    <>
                      <Tag tone="success">{t(`${k}.verified`)}</Tag>
                      {c.oauth ? <Tag>OAuth</Tag> : null}
                    </>
                  }
                  action={
                    c.remote_url_template ? (
                      <button
                        type="button"
                        className={outlineBtn}
                        onClick={() => hub.openRemote({ url: String(c.remote_url || ""), displayName: String(c.title || id), connectorId: id })}
                      >
                        {t(`${k}.configure_url`)}
                      </button>
                    ) : (
                      <button type="button" className={solidBtn} disabled={busyInstall} onClick={() => void hub.installFromCatalog(id, c)}>
                        {installing ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Download className="h-3.5 w-3.5" aria-hidden />}
                        {t(`${k}.install`)}
                      </button>
                    )
                  }
                />
              );
            })}
          </ul>
        </section>
      )}

      {hub.marketCategory !== "official" && (
        <section aria-labelledby="hub-community" aria-busy={hub.marketLoading}>
          <div className="mb-3 flex items-baseline gap-3 px-1">
            <h2 id="hub-community" className="text-lg font-semibold tracking-[-0.015em]">
              {t(`${k}.community_title`)}
            </h2>
            {!hub.marketLoading && <span className="text-sm tabular-nums text-muted-foreground">{hub.communityShown.length}</span>}
          </div>

          {hub.marketLoading ? (
            <div className="flex items-center gap-2 px-1 py-10 text-sm text-muted-foreground" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t(`${k}.searching`)}
            </div>
          ) : hub.communityShown.length === 0 ? (
            <div className="rounded-3xl border border-dashed border-border px-6 py-14 text-center">
              <h3 className="text-base font-semibold tracking-[-0.015em]">{t(`${k}.empty_title`)}</h3>
              <p className="mx-auto mt-1.5 max-w-[46ch] text-sm text-muted-foreground">{t(`${k}.empty_body`)}</p>
            </div>
          ) : (
            <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {hub.communityShown.map((item: any) => {
                const doc = docUrlFor(item);
                const thirdPartyOAuth = item.install_type === "remote" && item.source !== "Smithery";
                const catalogOnly = item.source === "Smithery" && (item.catalog_only || !doc?.includes("github.com"));
                const icon = item.icon_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={item.icon_url} alt="" className="h-full w-full object-contain p-1.5" onError={(e) => ((e.target as HTMLElement).style.display = "none")} />
                ) : catalogOnly || thirdPartyOAuth ? (
                  <Globe className="h-[18px] w-[18px]" />
                ) : (
                  <Box className="h-[18px] w-[18px]" />
                );
                return (
                  <CardShell
                    key={item.id}
                    icon={icon}
                    title={item.name}
                    href={doc}
                    subtitle={item.source}
                    description={item.description || t(`${k}.no_description`)}
                    tags={
                      catalogOnly ? (
                        <>
                          <Tag>{t(`${k}.tag_catalog`)}</Tag>
                          {item.verified && <Tag tone="success">{t(`${k}.verified`)}</Tag>}
                        </>
                      ) : thirdPartyOAuth ? (
                        <Tag tone="warning">{t(`${k}.tag_unverified`)}</Tag>
                      ) : (
                        <Tag>
                          <Sparkles className="h-3 w-3" aria-hidden />
                          {t(`${k}.tag_ai`)}
                        </Tag>
                      )
                    }
                    action={
                      catalogOnly ? (
                        doc ? (
                          <a href={doc} target="_blank" rel="noopener noreferrer" className={outlineBtn}>
                            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                            {t(`${k}.view`)}
                          </a>
                        ) : (
                          <span className="text-xs text-muted-foreground">{t(`${k}.catalog_only`)}</span>
                        )
                      ) : (
                        <button
                          type="button"
                          className={outlineBtn}
                          disabled={busyInstall}
                          onClick={() => hub.openWizardForMarket(item, thirdPartyOAuth)}
                        >
                          <Download className="h-3.5 w-3.5" aria-hidden />
                          {t(`${k}.install`)}
                        </button>
                      )
                    }
                  />
                );
              })}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
