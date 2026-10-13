"use client";

import { useEffect, useState } from "react";
import { GitBranch, Globe, LayoutGrid, List, Loader2, Package, Plus, Sparkles } from "lucide-react";
import { cn } from "@/lib/cn";
import { PageToast } from "@/components/PageToast";
import { Dialog } from "@/components/profiles/Dialog";
import { ghostBtn, inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";
import { Select } from "@/components/ui/Select";
import { SearchField } from "@/components/ui/SearchField";
import { DeleteDialog } from "@/components/ui/ConfirmDialogs";
import { McpIntegrityBanner } from "@/components/McpIntegrityBanner";
import { RemoteMcpInstallModal } from "@/components/RemoteMcpInstallModal";
import { DynamicWizardModal } from "@/components/DynamicWizardModal";
import { McpToolsManageModal } from "@/components/McpToolsManageModal";
import { Catalog } from "@/components/hub/Catalog";
import { ConfigDialog } from "@/components/hub/ConfigDialog";
import { ServerList } from "@/components/hub/ServerList";
import { useHub, type HubTab, type StatusFilter } from "@/components/hub/useHub";

function chatUiAdvisorUrl(slug: string): string {
  if (typeof window === "undefined") return "/";
  const { hostname, port, protocol, origin } = window.location;
  const base = port === "3870" || port === "" ? `${protocol}//${hostname}:8003` : origin;
  return `${base}/?profile=mcp_integration_advisor&context=${encodeURIComponent(slug)}`;
}

export default function HubPage() {
  const hub = useHub();
  const { t, k } = hub;
  const [view, setView] = useState<"table" | "cards">("table");
  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- read after mount to keep SSR markup stable
      if (localStorage.getItem("aion_hub_view") === "cards") setView("cards");
    } catch {}
  }, []);
  const pickView = (v: "table" | "cards") => {
    setView(v);
    try {
      localStorage.setItem("aion_hub_view", v);
    } catch {}
  };

  const tabs: { id: HubTab; label: string; count?: number }[] = [
    { id: "installed", label: t(`${k}.tabs.installed`), count: hub.counts.all },
    { id: "catalog", label: t(`${k}.tabs.catalog`) },
  ];

  const statusChips: { id: StatusFilter; label: string; count: number }[] = [
    { id: "all", label: t(`${k}.filter.all`), count: hub.counts.all },
    ...(hub.counts.attention > 0 ? [{ id: "attention" as const, label: t(`${k}.filter.attention`), count: hub.counts.attention }] : []),
    ...(hub.counts.disabled > 0 ? [{ id: "disabled" as const, label: t(`${k}.filter.disabled`), count: hub.counts.disabled }] : []),
  ];

  const filtering = hub.query.trim() !== "" || hub.runtimeFilter !== "all" || hub.statusFilter !== "all";

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <header className="flex flex-col gap-4 pt-2 lg:flex-row lg:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 max-w-[62ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
          {hub.sandboxBackend === "container" && (
            <p className="mt-2 inline-flex items-center gap-2 text-xs text-muted-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden />
              {t(`${k}.sandbox`)}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={outlineBtn} onClick={() => hub.setGithubOpen(true)}>
            <GitBranch className="h-3.5 w-3.5" aria-hidden />
            {t(`${k}.add_github`)}
          </button>
          <button type="button" className={outlineBtn} onClick={() => hub.openRemote()}>
            <Globe className="h-3.5 w-3.5" aria-hidden />
            {t(`${k}.add_remote`)}
          </button>
          {hub.tab !== "catalog" && (
            <button type="button" className={solidBtn} onClick={() => hub.setTab("catalog")}>
              <Plus className="h-4 w-4" aria-hidden />
              {t(`${k}.add_catalog`)}
            </button>
          )}
        </div>
      </header>

      <div role="tablist" aria-label={t(`${k}.tabs.aria`)} className="flex gap-1 border-b border-border">
        {tabs.map((tb) => {
          const active = hub.tab === tb.id;
          return (
            <button
              key={tb.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => hub.setTab(tb.id)}
              className={cn(
                "focus-ring -mb-px flex items-center gap-2 border-b-2 px-3.5 pb-3 pt-1 text-sm font-medium transition-colors",
                active ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {tb.label}
              {tb.count !== undefined && <span className="text-xs tabular-nums text-muted-foreground">{tb.count}</span>}
            </button>
          );
        })}
      </div>

      {hub.tab === "installed" ? (
        <section className="flex flex-col gap-4" role="tabpanel" aria-label={tabs[0].label}>
          <McpIntegrityBanner onRepaired={hub.refreshAll} />

          {!hub.installedLoaded ? (
            <div className="flex items-center gap-2 px-1 py-10 text-sm text-muted-foreground" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t(`${k}.loading`)}
            </div>
          ) : hub.counts.all === 0 ? (
            <div className="flex flex-col items-center rounded-3xl border border-dashed border-border px-6 py-20 text-center">
              <Package className="mb-4 h-8 w-8 text-muted-foreground" strokeWidth={1.5} aria-hidden />
              <h2 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.empty.title`)}</h2>
              <p className="mt-1.5 max-w-[46ch] text-sm text-muted-foreground">{t(`${k}.empty.body`)}</p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                <button type="button" className={solidBtn} onClick={() => hub.setTab("catalog")}>
                  <Plus className="h-4 w-4" aria-hidden />
                  {t(`${k}.add_catalog`)}
                </button>
                <button type="button" className={outlineBtn} onClick={() => hub.setGithubOpen(true)}>
                  <GitBranch className="h-3.5 w-3.5" aria-hidden />
                  {t(`${k}.add_github`)}
                </button>
                <button type="button" className={outlineBtn} onClick={() => hub.openRemote()}>
                  <Globe className="h-3.5 w-3.5" aria-hidden />
                  {t(`${k}.add_remote`)}
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                <div className="lg:w-80">
                  <SearchField value={hub.query} onChange={hub.setQuery} placeholder={t(`${k}.list.search`)} />
                </div>
                <div role="group" aria-label={t(`${k}.filter.aria`)} className="flex flex-wrap gap-1.5">
                  {statusChips.map((c) => {
                    const active = hub.statusFilter === c.id;
                    return (
                      <button
                        key={c.id}
                        type="button"
                        aria-pressed={active}
                        onClick={() => hub.setStatusFilter(c.id)}
                        className={cn(
                          "focus-ring rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors",
                          active
                            ? "border-foreground bg-foreground text-background"
                            : "border-border bg-card text-muted-foreground hover:border-foreground/30 hover:text-foreground",
                        )}
                      >
                        {c.label} <span className="tabular-nums opacity-70">{c.count}</span>
                      </button>
                    );
                  })}
                </div>
                <div className="lg:ml-auto lg:w-56">
                  <Select
                    size="sm"
                    className="bg-card"
                    value={hub.runtimeFilter}
                    onChange={hub.setRuntimeFilter}
                    aria-label={t(`${k}.list.runtime_aria`)}
                    options={(["all", "built_in", "stdio", "sse", "remote-bridge", "in_process"] as const).map((id) => ({
                      value: id,
                      label: t(`${k}.runtime.${id}`),
                    }))}
                  />
                </div>
                <div role="group" aria-label={t(`${k}.view.aria`)} className="inline-flex shrink-0 rounded-xl border border-border bg-card p-0.5">
                  {([["table", List], ["cards", LayoutGrid]] as const).map(([id, Icon]) => (
                    <button
                      key={id}
                      type="button"
                      aria-pressed={view === id}
                      aria-label={t(`${k}.view.${id}`)}
                      title={t(`${k}.view.${id}`)}
                      onClick={() => pickView(id)}
                      className={cn(
                        "focus-ring inline-flex h-9 w-9 items-center justify-center rounded-[10px] transition-colors",
                        view === id ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      <Icon className="h-4 w-4" aria-hidden />
                    </button>
                  ))}
                </div>
              </div>

              {hub.visibleRows.length === 0 ? (
                <div className="rounded-3xl border border-dashed border-border px-6 py-14 text-center">
                  <h2 className="text-base font-semibold tracking-[-0.015em]">{t(`${k}.list.no_match_title`)}</h2>
                  <p className="mt-1.5 text-sm text-muted-foreground">{t(`${k}.list.no_match_body`)}</p>
                  {filtering && (
                    <button
                      type="button"
                      className={cn(ghostBtn, "mt-4")}
                      onClick={() => {
                        hub.setQuery("");
                        hub.setRuntimeFilter("all");
                        hub.setStatusFilter("all");
                      }}
                    >
                      {t(`${k}.list.clear`)}
                    </button>
                  )}
                </div>
              ) : (
                <ServerList
                  items={hub.visibleRows}
                  view={view}
                  loading={hub.busy}
                  probingSlug={hub.probingSlug}
                  onEdit={(name, config) => void hub.openConfig(name, config as Record<string, unknown>)}
                  onProbe={(name) => void hub.probe(name)}
                  onWizard={hub.openWizardFor}
                  onManageTools={hub.setManageToolsSlug}
                  onDelete={(name) => void hub.startDelete(name)}
                  onAdvisor={hub.openAdvisorFor}
                  advisorUrl={chatUiAdvisorUrl}
                />
              )}
            </>
          )}
        </section>
      ) : (
        <section role="tabpanel" aria-label={tabs[1].label}>
          <Catalog hub={hub} />
        </section>
      )}

      {hub.editing && <ConfigDialog key={hub.editing.name} hub={hub} />}

      {hub.githubOpen && (
        <Dialog title={t(`${k}.github.title`)} closeLabel={t(`${k}.github.cancel`)} onClose={() => hub.setGithubOpen(false)} className="max-w-xl">
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              void hub.analyzeGithub();
            }}
          >
            <p className="text-sm text-muted-foreground">{t(`${k}.github.body`)}</p>
            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">{t(`${k}.github.url`)}</span>
              <input
                autoFocus
                type="url"
                value={hub.githubUrl}
                onChange={(e) => hub.setGithubUrl(e.target.value)}
                placeholder="https://github.com/ai-zerolab/mcp-email-server"
                className={cn(inputCls, "font-mono")}
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">
                {t(`${k}.github.name`)} <span className="font-normal text-muted-foreground">· {t(`${k}.github.optional`)}</span>
              </span>
              <input
                type="text"
                value={hub.githubName}
                onChange={(e) => hub.setGithubName(e.target.value)}
                placeholder="MCP Email Server"
                className={inputCls}
              />
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" className={ghostBtn} onClick={() => hub.setGithubOpen(false)} disabled={hub.analyzingGithub}>
                {t(`${k}.github.cancel`)}
              </button>
              <button type="submit" className={solidBtn} disabled={!hub.githubUrl.trim() || hub.analyzingGithub}>
                {hub.analyzingGithub ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Sparkles className="h-3.5 w-3.5" aria-hidden />}
                {hub.analyzingGithub ? t(`${k}.github.analyzing`) : t(`${k}.github.analyze`)}
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {hub.deleteSlug && (
        <DeleteDialog name={hub.deleteSlug} busy={hub.busy} ns={`${k}.delete`} t={t} onConfirm={() => void hub.confirmDelete()} onClose={() => hub.setDeleteSlug(null)} />
      )}

      {hub.blockedBy && (
        <Dialog title={t(`${k}.blocked.title`)} closeLabel={t(`${k}.blocked.close`)} onClose={() => hub.setBlockedBy(null)}>
          <div className="flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">{t(`${k}.blocked.body`, { name: hub.blockedBy.slug })}</p>
            <ul className="flex flex-col gap-1">
              {hub.blockedBy.profiles.map((p) => (
                <li key={p} className="rounded-xl bg-secondary px-3 py-2 text-sm font-medium">
                  {p}
                </li>
              ))}
            </ul>
            <p className="text-sm text-muted-foreground">{t(`${k}.blocked.hint`)}</p>
            <div className="flex justify-end">
              <button type="button" className={solidBtn} autoFocus onClick={() => hub.setBlockedBy(null)}>
                {t(`${k}.blocked.close`)}
              </button>
            </div>
          </div>
        </Dialog>
      )}

      {hub.adviseOpen && (
        <Dialog title={t(`${k}.advisor.title`)} closeLabel={t(`${k}.advisor.close`)} onClose={() => hub.setAdviseOpen(false)} className="max-w-2xl">
          <div className="flex flex-col gap-4">
            {hub.adviseLoading ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                {t(`${k}.advisor.loading`)}
              </p>
            ) : (
              <pre className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap rounded-2xl bg-secondary/60 p-4 font-mono text-xs leading-relaxed">
                {hub.adviseResult || t(`${k}.advisor.empty`)}
              </pre>
            )}
            <div className="flex justify-end">
              <button type="button" className={solidBtn} onClick={() => hub.setAdviseOpen(false)}>
                {t(`${k}.advisor.close`)}
              </button>
            </div>
          </div>
        </Dialog>
      )}

      <RemoteMcpInstallModal
        open={hub.remoteOpen}
        onClose={() => hub.setRemoteOpen(false)}
        presets={hub.featured}
        initialUrl={hub.remoteSeed.url || ""}
        initialDisplayName={hub.remoteSeed.displayName || ""}
        initialConnectorId={hub.remoteSeed.connectorId || ""}
        installing={hub.installingId === "remote:manual"}
        onInstallStart={hub.installRemoteStart}
        onInstallEnd={hub.installRemoteEnd}
        onInstalled={(slug) => {
          hub.setToast({ message: t(`${k}.toast.remote_installed`, { slug }), variant: "success" });
          void hub.fetchRegistry();
          hub.setTab("installed");
        }}
      />

      <DynamicWizardModal
        open={hub.wizardOpen}
        target={hub.wizardTarget}
        onClose={hub.closeWizard}
        onInstalled={(slug) => {
          hub.refreshAll();
          hub.setTab("installed");
          hub.setToast({ message: t(`${k}.toast.wizard_installed`, { slug }), variant: "success" });
        }}
      />

      <McpToolsManageModal
        serverSlug={hub.manageToolsSlug}
        open={Boolean(hub.manageToolsSlug)}
        onClose={() => hub.setManageToolsSlug(null)}
        onSaved={hub.refreshAll}
      />

      <PageToast toast={hub.toast} onDismiss={() => hub.setToast(null)} />
    </div>
  );
}
