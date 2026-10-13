"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowUpRight,
  Download,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
  TriangleAlert,
  Upload,
  Undo2,
  Wand2,
  X,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { getLocale } from "@/lib/i18n/i18n-store";
import { PageToast } from "@/components/PageToast";
import { BlockMarkdownEditor } from "@/components/BlockMarkdownEditor";
import { Dialog } from "@/components/profiles/Dialog";
import { ghostBtn, inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";
import { SearchField } from "@/components/ui/SearchField";
import { DeleteDialog, LeaveDialog } from "@/components/ui/ConfirmDialogs";
import { SkillPreview } from "@/components/skills/SkillPreview";
import { PickerList, type PickerItem } from "@/components/profiles/PickerList";
import { NATIVE_TOOL_BUNDLES, profileSlug, useProfiles } from "@/components/profiles/useProfiles";

type Tab = "instructions" | "skills" | "tools";

/** All / attached segmented control shared by the skills and tools pickers. */
function AttachedFilter({
  value,
  onChange,
  ariaLabel,
  allLabel,
  attachedLabel,
}: {
  value: boolean;
  onChange: (attachedOnly: boolean) => void;
  ariaLabel: string;
  allLabel: string;
  attachedLabel: string;
}) {
  return (
    <div role="group" aria-label={ariaLabel} className="inline-flex shrink-0 rounded-xl border border-border bg-background p-0.5">
      {[
        { v: false, label: allLabel },
        { v: true, label: attachedLabel },
      ].map((o) => (
        <button
          key={String(o.v)}
          type="button"
          aria-pressed={value === o.v}
          onClick={() => onChange(o.v)}
          className={cn(
            "focus-ring h-9 rounded-[10px] px-3.5 text-sm font-medium transition-colors",
            value === o.v ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function ProfilesPage() {
  const t = useT();
  const k = "admin_profiles";
  const p = useProfiles();
  const { selected, dirty, isPersisted } = p;

  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<Tab>("instructions");
  const [editing, setEditing] = useState(false); // mobile: editor replaces the list
  const [skillQuery, setSkillQuery] = useState("");
  const [attachedOnly, setAttachedOnly] = useState(false);
  const [toolQuery, setToolQuery] = useState("");
  const [toolsAttachedOnly, setToolsAttachedOnly] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardPrompt, setWizardPrompt] = useState("");
  const [leaveAction, setLeaveAction] = useState<(() => void) | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [previewSkill, setPreviewSkill] = useState<string | null>(null);

  // Ctrl/Cmd+S saves the open profile instead of the browser's "save page".
  const canSave = !!selected && !p.saving && (!isPersisted || dirty);
  const { save } = p;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (canSave) void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canSave, save]);

  const plural = (key: string, count: number) => {
    const form = new Intl.PluralRules(getLocale()).select(count) === "one" ? "one" : "other";
    return t(`${k}.list.${key}_${form}`, { count });
  };

  // Runs `action` now, or after the admin confirms discarding unsaved changes.
  const guard = (action: () => void) => {
    if (dirty) setLeaveAction(() => action);
    else action();
  };

  const open = (action: () => void) => {
    guard(() => {
      setTab("instructions");
      setAiOpen(false);
      setEditing(true);
      action();
    });
  };

  const currentSlug = selected ? profileSlug(selected) : null;

  const visibleProfiles = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return p.profiles;
    return p.profiles.filter((x) => x.name.toLowerCase().includes(q) || (x.description || "").toLowerCase().includes(q));
  }, [p.profiles, query]);

  const skillItems: PickerItem[] = useMemo(() => {
    if (!selected) return [];
    const q = skillQuery.trim().toLowerCase();
    return Object.entries(p.skills)
      .filter(([name, info]) => {
        if (attachedOnly && !selected.skills.includes(name)) return false;
        if (!q) return true;
        return (
          name.toLowerCase().includes(q) ||
          (info.description || "").toLowerCase().includes(q) ||
          (info.tags || []).some((tag) => tag.toLowerCase().includes(q))
        );
      })
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, info]) => ({
        id: name,
        description: info.description || t(`${k}.skills.no_description`),
        on: selected.skills.includes(name),
        critical: selected.critical_skills.includes(name),
      }));
  }, [selected, p.skills, skillQuery, attachedOnly, t]);

  const toolMatches = (id: string, desc: string, on: boolean) => {
    if (toolsAttachedOnly && !on) return false;
    const q = toolQuery.trim().toLowerCase();
    return !q || id.toLowerCase().includes(q) || desc.toLowerCase().includes(q);
  };

  const nativeItems: PickerItem[] = useMemo(() => {
    if (!selected) return [];
    return NATIVE_TOOL_BUNDLES.map((id) => ({
      id,
      description: p.mcpDescriptions[id] || t(`${k}.tools.native_${id}`),
      on: selected.native_tool_groups.includes(id),
    })).filter((it) => toolMatches(it.id, it.description, it.on));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, p.mcpDescriptions, toolQuery, toolsAttachedOnly, t]);

  const mcpItems: PickerItem[] = useMemo(() => {
    if (!selected) return [];
    return Object.keys(p.mcpDescriptions)
      .filter((id) => !NATIVE_TOOL_BUNDLES.includes(id))
      .sort()
      .map((id) => {
        const on = selected.mcp_servers.includes(id);
        const waiting = p.mcpAwaitingSetup(id);
        return {
          id,
          description: p.mcpDescriptions[id] || t(`${k}.tools.no_description`),
          on,
          blockedLabel: waiting ? t(`${k}.tools.setup_needed`) : undefined,
        };
      })
      .filter((it) => (!it.blockedLabel || it.on) && toolMatches(it.id, it.description, it.on));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, p.mcpDescriptions, p.mcpAwaitingSetup, toolQuery, toolsAttachedOnly, t]);

  const hasBlockedMcp = !!selected && selected.mcp_servers.some((s) => p.mcpAwaitingSetup(s));

  const runWizard = async () => {
    if (await p.generate(wizardPrompt)) {
      setWizardOpen(false);
      setWizardPrompt("");
      setTab("instructions");
      setEditing(true);
    }
  };

  const runRefine = async () => {
    if (await p.refine(aiPrompt)) setAiPrompt("");
  };

  const remove = async () => {
    if (await p.remove()) {
      setDeleteOpen(false);
      setEditing(false);
    }
  };

  const stateLabel = !isPersisted
    ? t(`${k}.editor.state_draft`)
    : dirty
      ? t(`${k}.editor.state_dirty`)
      : t(`${k}.editor.state_saved`);

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "instructions", label: t(`${k}.editor.tab_instructions`) },
    { id: "skills", label: t(`${k}.editor.tab_skills`), count: selected?.skills.length },
    {
      id: "tools",
      label: t(`${k}.editor.tab_tools`),
      count: selected ? selected.mcp_servers.length + selected.native_tool_groups.length : undefined,
    },
  ];

  const showEmpty = p.listLoaded && p.profiles.length === 0 && !selected;

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={outlineBtn} onClick={() => setWizardOpen(true)}>
            <Wand2 className="h-3.5 w-3.5" aria-hidden />
            {t(`${k}.ai_create`)}
          </button>
          <button type="button" className={solidBtn} onClick={() => open(p.createBlank)}>
            <Plus className="h-4 w-4" aria-hidden />
            {t(`${k}.new`)}
          </button>
        </div>
      </header>

      {showEmpty ? (
        <div className="flex flex-col items-center rounded-3xl border border-dashed border-border px-6 py-20 text-center">
          <h2 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.empty.title`)}</h2>
          <p className="mt-1.5 max-w-[46ch] text-sm text-muted-foreground">{t(`${k}.empty.body`)}</p>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            <button type="button" className={solidBtn} onClick={() => open(p.createBlank)}>
              <Plus className="h-4 w-4" aria-hidden />
              {t(`${k}.new`)}
            </button>
            <button type="button" className={outlineBtn} onClick={() => setWizardOpen(true)}>
              <Wand2 className="h-3.5 w-3.5" aria-hidden />
              {t(`${k}.ai_create`)}
            </button>
            <button type="button" className={outlineBtn} onClick={p.importFile}>
              <Upload className="h-3.5 w-3.5" aria-hidden />
              {t(`${k}.import`)}
            </button>
          </div>
        </div>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[17rem_minmax(0,1fr)]">
          {/* ───────── List ───────── */}
          <aside className={cn("flex flex-col gap-3", editing && selected && "hidden lg:flex")}>
            <SearchField value={query} onChange={setQuery} placeholder={t(`${k}.list.search`)} />

            {!p.listLoaded ? (
              <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground" role="status">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                {t(`${k}.loading`)}
              </div>
            ) : (
              <nav aria-label={t(`${k}.list.aria`)}>
                <ul className="flex flex-col gap-0.5">
                  {selected && !isPersisted && (
                    <li>
                      <div
                        aria-current="true"
                        className="rounded-xl bg-secondary px-3 py-2.5"
                      >
                        <div className="truncate text-sm font-medium">{selected.name || t(`${k}.list.draft`)}</div>
                        <div className="text-xs text-muted-foreground">{t(`${k}.list.unsaved`)}</div>
                      </div>
                    </li>
                  )}
                  {visibleProfiles.map((row) => {
                    const slug = profileSlug(row);
                    const active = isPersisted && slug === currentSlug;
                    return (
                      <li key={slug}>
                        <button
                          type="button"
                          aria-current={active ? "true" : undefined}
                          onClick={() => !active && open(() => void p.select(slug))}
                          className={cn(
                            "focus-ring w-full rounded-xl px-3 py-2.5 text-left transition-colors",
                            active ? "bg-secondary" : "hover:bg-secondary/60",
                          )}
                        >
                          <div className="flex items-center gap-2">
                            <span className="truncate text-sm font-medium">{row.name}</span>
                            {active && dirty && (
                              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" title={t(`${k}.list.unsaved`)} />
                            )}
                          </div>
                          <div className="mt-0.5 truncate text-xs text-muted-foreground tabular-nums">
                            {plural("meta_skills", row.skills.length)} · {plural("meta_tools", row.mcp_servers.length + row.native_tool_groups.length)}
                          </div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
                {visibleProfiles.length === 0 && (
                  <p className="px-3 py-6 text-sm text-muted-foreground">{t(`${k}.list.empty_search`)}</p>
                )}
              </nav>
            )}

            <div className="mt-1 flex flex-wrap gap-1 border-t border-border/50 pt-3">
              <button type="button" className={ghostBtn} onClick={p.importFile}>
                <Upload className="h-3.5 w-3.5" aria-hidden />
                {t(`${k}.import`)}
              </button>
              {p.profiles.length > 0 && (
                <button type="button" className={ghostBtn} onClick={p.exportAll}>
                  <Download className="h-3.5 w-3.5" aria-hidden />
                  {t(`${k}.export_all`)}
                </button>
              )}
            </div>
          </aside>

          {/* ───────── Editor ───────── */}
          <section className={cn("min-w-0", !(editing && selected) && "hidden lg:block")} aria-busy={p.loadingProfile}>
            {!selected ? (
              <div className="rounded-3xl border border-dashed border-border px-6 py-20 text-center">
                <h2 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.pick.title`)}</h2>
                <p className="mt-1.5 text-sm text-muted-foreground">{t(`${k}.pick.body`)}</p>
              </div>
            ) : (
              <div className={cn("flex flex-col gap-4 transition-opacity", p.loadingProfile && "opacity-60")}>
                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" className={cn(ghostBtn, "-ml-2 lg:hidden")} onClick={() => guard(() => setEditing(false))}>
                    <ArrowLeft className="h-4 w-4" aria-hidden />
                    {t(`${k}.list.back`)}
                  </button>
                  <span
                    role="status"
                    className={cn("text-sm tabular-nums", dirty || !isPersisted ? "font-medium text-warning" : "text-muted-foreground")}
                  >
                    {stateLabel}
                  </span>
                  <div className="ml-auto flex flex-wrap items-center gap-1">
                    {isPersisted && dirty && (
                      <button type="button" className={ghostBtn} onClick={() => void p.select(currentSlug!)}>
                        <Undo2 className="h-3.5 w-3.5" aria-hidden />
                        {t(`${k}.editor.revert`)}
                      </button>
                    )}
                    {isPersisted ? (
                      <>
                        <button type="button" className={ghostBtn} onClick={p.exportOne}>
                          <Download className="h-3.5 w-3.5" aria-hidden />
                          <span className="hidden sm:inline">{t(`${k}.editor.export`)}</span>
                          <span className="sr-only sm:hidden">{t(`${k}.editor.export`)}</span>
                        </button>
                        <button
                          type="button"
                          className={cn(ghostBtn, "hover:text-destructive")}
                          onClick={() => setDeleteOpen(true)}
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden />
                          <span className="hidden sm:inline">{t(`${k}.editor.delete`)}</span>
                          <span className="sr-only sm:hidden">{t(`${k}.editor.delete`)}</span>
                        </button>
                      </>
                    ) : (
                      <button type="button" className={ghostBtn} onClick={() => guard(() => (p.discardDraft(), setEditing(false)))}>
                        <X className="h-3.5 w-3.5" aria-hidden />
                        {t(`${k}.editor.discard_draft`)}
                      </button>
                    )}
                    <button type="button" className={cn(solidBtn, "ml-1")} onClick={p.save} disabled={p.saving || (isPersisted && !dirty)}>
                      {p.saving && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
                      {p.saving ? t(`${k}.editor.saving`) : t(`${k}.editor.save`)}
                    </button>
                  </div>
                </div>

                <div className="rounded-3xl border border-border/70 bg-card">
                  <div className="grid gap-4 p-5 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] sm:p-6">
                    <label className="flex flex-col gap-1.5">
                      <span className="text-sm font-medium">{t(`${k}.editor.name`)}</span>
                      <input
                        type="text"
                        value={selected.name}
                        onChange={(e) => p.update({ name: e.target.value })}
                        placeholder={t(`${k}.editor.name_placeholder`)}
                        className={cn(inputCls, "font-medium")}
                      />
                    </label>
                    <label className="flex flex-col gap-1.5">
                      <span className="text-sm font-medium">{t(`${k}.editor.description`)}</span>
                      <input
                        type="text"
                        value={selected.description || ""}
                        onChange={(e) => p.update({ description: e.target.value })}
                        placeholder={t(`${k}.editor.description_placeholder`)}
                        className={inputCls}
                      />
                    </label>
                  </div>

                  <div className="flex items-center gap-2 border-t border-border/60 px-3 sm:px-4">
                    <div role="tablist" aria-label={t(`${k}.editor.tabs_aria`)} className="no-scrollbar flex min-w-0 flex-1 gap-1 overflow-x-auto">
                      {tabs.map((x) => {
                        const active = tab === x.id;
                        return (
                          <button
                            key={x.id}
                            type="button"
                            role="tab"
                            id={`tab-${x.id}`}
                            aria-selected={active}
                            aria-controls="profile-panel"
                            onClick={() => setTab(x.id)}
                            className={cn(
                              "focus-ring relative inline-flex h-12 shrink-0 items-center gap-2 px-3 text-sm font-medium transition-colors",
                              active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                            )}
                          >
                            {x.label}
                            {x.count !== undefined && x.count > 0 && (
                              <span className="rounded-full bg-secondary px-1.5 py-px text-xs tabular-nums text-muted-foreground">
                                {x.count}
                              </span>
                            )}
                            <span
                              aria-hidden
                              className={cn(
                                "absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-foreground transition-opacity",
                                active ? "opacity-100" : "opacity-0",
                              )}
                            />
                          </button>
                        );
                      })}
                    </div>
                    <button
                      type="button"
                      onClick={() => setAiOpen((v) => !v)}
                      aria-expanded={aiOpen}
                      className={cn(ghostBtn, "shrink-0", aiOpen && "bg-secondary text-foreground")}
                    >
                      <Sparkles className="h-3.5 w-3.5" aria-hidden />
                      <span className="hidden sm:inline">{t(`${k}.ai.toggle`)}</span>
                      <span className="sr-only sm:hidden">{t(`${k}.ai.toggle`)}</span>
                    </button>
                  </div>

                  {aiOpen && (
                    <form
                      className="flex flex-col gap-2 border-t border-border/60 bg-secondary/30 p-3 sm:flex-row sm:p-4"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void runRefine();
                      }}
                    >
                      <input
                        type="text"
                        value={aiPrompt}
                        onChange={(e) => setAiPrompt(e.target.value)}
                        placeholder={t(`${k}.ai.placeholder`)}
                        aria-label={t(`${k}.ai.toggle`)}
                        className={cn(inputCls, "flex-1")}
                      />
                      <button type="submit" className={solidBtn} disabled={p.refineLoading || !aiPrompt.trim()}>
                        {p.refineLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Wand2 className="h-3.5 w-3.5" aria-hidden />}
                        {p.refineLoading ? t(`${k}.ai.applying`) : t(`${k}.ai.apply`)}
                      </button>
                    </form>
                  )}

                  <div id="profile-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="border-t border-border/60 p-4 sm:p-5">
                    {tab === "instructions" && (
                      <BlockMarkdownEditor
                        value={selected.instructions || ""}
                        onChange={(v) => p.update({ instructions: v })}
                        height={480}
                        placeholder={t(`${k}.editor.instructions_placeholder`)}
                        allowTasks={false}
                      />
                    )}

                    {tab === "skills" && (
                      <div className="flex flex-col gap-4">
                        <div className="flex flex-col gap-2 sm:flex-row">
                          <div className="flex-1">
                            <SearchField value={skillQuery} onChange={setSkillQuery} placeholder={t(`${k}.skills.search`)} className="bg-background" />
                          </div>
                          <AttachedFilter
                            value={attachedOnly}
                            onChange={setAttachedOnly}
                            ariaLabel={t(`${k}.skills.filter_aria`)}
                            allLabel={t(`${k}.skills.filter_all`)}
                            attachedLabel={t(`${k}.skills.filter_attached`)}
                          />
                        </div>
                        {skillItems.length > 0 ? (
                          <>
                            <PickerList
                              items={skillItems}
                              onToggle={p.toggleSkill}
                              onCritical={p.toggleCritical}
                              onPreview={setPreviewSkill}
                              previewLabel={t(`${k}.skills.preview`)}
                              criticalOn={t(`${k}.skills.critical_on`)}
                              criticalOff={t(`${k}.skills.critical_off`)}
                            />
                            <p className="px-1 text-xs text-muted-foreground">{t(`${k}.skills.critical_hint`)}</p>
                          </>
                        ) : (
                          <p className="py-10 text-center text-sm text-muted-foreground">{t(`${k}.skills.none`)}</p>
                        )}
                      </div>
                    )}

                    {tab === "tools" && (
                      <div className="flex flex-col gap-5">
                        <div className="flex flex-col gap-2 sm:flex-row">
                          <div className="flex-1">
                            <SearchField value={toolQuery} onChange={setToolQuery} placeholder={t(`${k}.tools.search`)} className="bg-background" />
                          </div>
                          <AttachedFilter
                            value={toolsAttachedOnly}
                            onChange={setToolsAttachedOnly}
                            ariaLabel={t(`${k}.tools.filter_aria`)}
                            allLabel={t(`${k}.tools.filter_all`)}
                            attachedLabel={t(`${k}.tools.filter_attached`)}
                          />
                        </div>
                        {hasBlockedMcp && (
                          <div className="flex items-start gap-3 rounded-2xl bg-warning/10 px-4 py-3 text-sm" role="alert">
                            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
                            <span className="flex-1">{t(`${k}.tools.setup_banner`)}</span>
                            <Link href="/hub" className="focus-ring inline-flex shrink-0 items-center gap-1 rounded-lg font-medium underline underline-offset-4">
                              {t(`${k}.tools.manage_hub`)}
                              <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
                            </Link>
                          </div>
                        )}
                        {nativeItems.length > 0 && (
                          <section className="flex flex-col gap-2">
                            <h3 className="px-1 text-sm font-semibold">{t(`${k}.tools.builtin`)}</h3>
                            <PickerList items={nativeItems} onToggle={p.toggleNative} />
                          </section>
                        )}
                        {mcpItems.length > 0 && (
                          <section className="flex flex-col gap-2">
                            <h3 className="px-1 text-sm font-semibold">{t(`${k}.tools.mcp`)}</h3>
                            <PickerList items={mcpItems} onToggle={p.toggleMcp} />
                          </section>
                        )}
                        {nativeItems.length === 0 && mcpItems.length === 0 && (
                          <p className="py-10 text-center text-sm text-muted-foreground">{t(`${k}.tools.none`)}</p>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </section>
        </div>
      )}

      {wizardOpen && (
        <Dialog title={t(`${k}.wizard.title`)} closeLabel={t(`${k}.wizard.cancel`)} onClose={() => setWizardOpen(false)} className="max-w-xl">
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              void runWizard();
            }}
          >
            <p className="text-sm text-muted-foreground">{t(`${k}.wizard.body`)}</p>
            <textarea
              autoFocus
              rows={5}
              value={wizardPrompt}
              onChange={(e) => setWizardPrompt(e.target.value)}
              placeholder={t(`${k}.wizard.placeholder`)}
              aria-label={t(`${k}.wizard.title`)}
              className={cn(inputCls, "resize-none")}
            />
            <div className="flex flex-wrap items-center gap-3">
              <span className="min-w-0 flex-1 text-xs text-muted-foreground">{t(`${k}.wizard.hint`)}</span>
              <button type="button" className={ghostBtn} onClick={() => setWizardOpen(false)}>
                {t(`${k}.wizard.cancel`)}
              </button>
              <button type="submit" className={solidBtn} disabled={p.wizardLoading || !wizardPrompt.trim()}>
                {p.wizardLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Wand2 className="h-3.5 w-3.5" aria-hidden />}
                {p.wizardLoading ? t(`${k}.wizard.generating`) : t(`${k}.wizard.generate`)}
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {previewSkill && <SkillPreview name={previewSkill} t={t} onClose={() => setPreviewSkill(null)} />}

      {deleteOpen && selected && (
        <DeleteDialog name={selected.name} busy={p.saving} ns={`${k}.delete`} t={t} onConfirm={remove} onClose={() => setDeleteOpen(false)} />
      )}

      {leaveAction && (
        <LeaveDialog
          ns={`${k}.leave`}
          t={t}
          onStay={() => setLeaveAction(null)}
          onLeave={() => {
            const go = leaveAction;
            setLeaveAction(null);
            go();
          }}
        />
      )}

      <PageToast toast={p.toast} onDismiss={() => p.setToast(null)} />
    </div>
  );
}
