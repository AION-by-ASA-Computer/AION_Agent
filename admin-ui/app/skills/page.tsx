"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Download, Loader2, Plus, Sparkles, Trash2, Undo2, Upload, Wand2, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { PageToast } from "@/components/PageToast";
import { BlockMarkdownEditor } from "@/components/BlockMarkdownEditor";
import { Dialog } from "@/components/profiles/Dialog";
import { ghostBtn, inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";
import { SearchField } from "@/components/ui/SearchField";
import { DeleteDialog, LeaveDialog } from "@/components/ui/ConfirmDialogs";
import { skillSlug, useSkills } from "@/components/skills/useSkills";

export default function SkillsPage() {
  const t = useT();
  const k = "admin_skills";
  const s = useSkills();
  const { selected, dirty, isPersisted } = s;

  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState(false); // mobile: editor replaces the list
  const [aiOpen, setAiOpen] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardPrompt, setWizardPrompt] = useState("");
  const [leaveAction, setLeaveAction] = useState<(() => void) | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [blockedBy, setBlockedBy] = useState<string[] | null>(null);

  // Ctrl/Cmd+S saves the open skill instead of the browser's "save page".
  const canSave = !!selected && !s.busy && (!isPersisted || dirty);
  const { save } = s;
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

  // Runs `action` now, or after the admin confirms discarding unsaved changes.
  const guard = (action: () => void) => {
    if (dirty) setLeaveAction(() => action);
    else action();
  };

  const open = (action: () => void) => {
    guard(() => {
      setAiOpen(false);
      setEditing(true);
      action();
    });
  };

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return s.names.filter((name) => {
      const info = s.skills[name];
      if (!q) return true;
      return (
        name.toLowerCase().includes(q) ||
        (info.description || "").toLowerCase().includes(q) ||
        (info.tags || []).some((tag) => tag.toLowerCase().includes(q))
      );
    });
  }, [s.names, s.skills, query]);

  const startDelete = async () => {
    if (!s.persistedName) return;
    const using = await s.profilesUsing(s.persistedName);
    if (using === null) return;
    if (using.length > 0) setBlockedBy(using);
    else setDeleteOpen(true);
  };

  const remove = async () => {
    if (await s.remove()) {
      setDeleteOpen(false);
      setEditing(false);
    }
  };

  const runWizard = async () => {
    if (await s.generate(wizardPrompt)) {
      setWizardOpen(false);
      setWizardPrompt("");
      setEditing(true);
    }
  };

  const runRefine = async () => {
    if (await s.refine(aiPrompt)) setAiPrompt("");
  };

  const renaming = isPersisted && !!selected && skillSlug(selected.name) !== s.persistedName;

  const stateLabel = !isPersisted
    ? t(`${k}.editor.state_draft`)
    : dirty
      ? t(`${k}.editor.state_dirty`)
      : t(`${k}.editor.state_saved`);

  const showEmpty = s.listLoaded && s.names.length === 0 && !selected;

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
          <button type="button" className={solidBtn} onClick={() => open(s.createBlank)}>
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
            <button type="button" className={solidBtn} onClick={() => open(s.createBlank)}>
              <Plus className="h-4 w-4" aria-hidden />
              {t(`${k}.new`)}
            </button>
            <button type="button" className={outlineBtn} onClick={() => setWizardOpen(true)}>
              <Wand2 className="h-3.5 w-3.5" aria-hidden />
              {t(`${k}.ai_create`)}
            </button>
            <button type="button" className={outlineBtn} onClick={() => open(() => s.importFile(() => setEditing(true)))}>
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

            {!s.listLoaded ? (
              <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground" role="status">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                {t(`${k}.loading`)}
              </div>
            ) : (
              <nav aria-label={t(`${k}.list.aria`)}>
                <ul className="flex flex-col gap-0.5">
                  {selected && !isPersisted && (
                    <li>
                      <div aria-current="true" className="rounded-xl bg-secondary px-3 py-2.5">
                        <div className="truncate text-sm font-medium">{selected.name || t(`${k}.list.draft`)}</div>
                        <div className="text-xs text-muted-foreground">{t(`${k}.list.unsaved`)}</div>
                      </div>
                    </li>
                  )}
                  {visible.map((name) => {
                    const info = s.skills[name];
                    const active = isPersisted && name === s.persistedName;
                    return (
                      <li key={name}>
                        <button
                          type="button"
                          aria-current={active ? "true" : undefined}
                          onClick={() => !active && open(() => void s.select(name))}
                          className={cn(
                            "focus-ring w-full rounded-xl px-3 py-2.5 text-left transition-colors",
                            active ? "bg-secondary" : "hover:bg-secondary/60",
                          )}
                        >
                          <div className="flex items-center gap-2">
                            <span className="truncate font-mono text-[13px] font-medium">{name}</span>
                            {active && dirty && (
                              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" title={t(`${k}.list.unsaved`)} />
                            )}
                          </div>
                          <div className="mt-0.5 truncate text-xs text-muted-foreground">
                            {info.description || t(`${k}.list.no_description`)}
                          </div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
                {visible.length === 0 && (
                  <p className="px-3 py-6 text-sm text-muted-foreground">{t(`${k}.list.empty_search`)}</p>
                )}
              </nav>
            )}

            <div className="mt-1 flex flex-wrap gap-1 border-t border-border/50 pt-3">
              <button type="button" className={ghostBtn} onClick={() => open(() => s.importFile(() => setEditing(true)))}>
                <Upload className="h-3.5 w-3.5" aria-hidden />
                {t(`${k}.import`)}
              </button>
              {s.names.length > 0 && (
                <button type="button" className={ghostBtn} onClick={s.exportAll}>
                  <Download className="h-3.5 w-3.5" aria-hidden />
                  {t(`${k}.export_all`)}
                </button>
              )}
            </div>
          </aside>

          {/* ───────── Editor ───────── */}
          <section className={cn("min-w-0", !(editing && selected) && "hidden lg:block")} aria-busy={s.loadingSkill}>
            {!selected ? (
              <div className="rounded-3xl border border-dashed border-border px-6 py-20 text-center">
                <h2 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.pick.title`)}</h2>
                <p className="mt-1.5 text-sm text-muted-foreground">{t(`${k}.pick.body`)}</p>
              </div>
            ) : (
              <div className={cn("flex flex-col gap-4 transition-opacity", s.loadingSkill && "opacity-60")}>
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
                      <button type="button" className={ghostBtn} onClick={() => void s.select(s.persistedName!)}>
                        <Undo2 className="h-3.5 w-3.5" aria-hidden />
                        {t(`${k}.editor.revert`)}
                      </button>
                    )}
                    {isPersisted ? (
                      <>
                        <button type="button" className={ghostBtn} onClick={s.exportOne}>
                          <Download className="h-3.5 w-3.5" aria-hidden />
                          <span className="hidden sm:inline">{t(`${k}.editor.export`)}</span>
                          <span className="sr-only sm:hidden">{t(`${k}.editor.export`)}</span>
                        </button>
                        <button type="button" className={cn(ghostBtn, "hover:text-destructive")} onClick={() => void startDelete()} disabled={s.busy}>
                          <Trash2 className="h-3.5 w-3.5" aria-hidden />
                          <span className="hidden sm:inline">{t(`${k}.editor.delete`)}</span>
                          <span className="sr-only sm:hidden">{t(`${k}.editor.delete`)}</span>
                        </button>
                      </>
                    ) : (
                      <button type="button" className={ghostBtn} onClick={() => guard(() => (s.discardDraft(), setEditing(false)))}>
                        <X className="h-3.5 w-3.5" aria-hidden />
                        {t(`${k}.editor.discard_draft`)}
                      </button>
                    )}
                    <button type="button" className={cn(solidBtn, "ml-1")} onClick={s.save} disabled={!canSave}>
                      {s.busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
                      {s.busy ? t(`${k}.editor.saving`) : t(`${k}.editor.save`)}
                    </button>
                  </div>
                </div>

                <div className="rounded-3xl border border-border/70 bg-card">
                  <div className="grid gap-4 p-5 sm:p-6 lg:grid-cols-2">
                    <label className="flex flex-col gap-1.5">
                      <span className="text-sm font-medium">{t(`${k}.editor.name`)}</span>
                      <input
                        type="text"
                        value={selected.name}
                        onChange={(e) => s.update({ name: e.target.value.toLowerCase().replace(/\s+/g, "_") })}
                        placeholder={t(`${k}.editor.name_placeholder`)}
                        aria-describedby={renaming ? "skill-name-hint" : undefined}
                        className={cn(inputCls, "font-mono")}
                      />
                      {renaming && (
                        <span id="skill-name-hint" className="text-xs text-muted-foreground">
                          {t(`${k}.editor.name_hint`)}
                        </span>
                      )}
                    </label>
                    <label className="flex flex-col gap-1.5">
                      <span className="text-sm font-medium">{t(`${k}.editor.tags`)}</span>
                      <input
                        type="text"
                        value={selected.tags}
                        onChange={(e) => s.update({ tags: e.target.value })}
                        placeholder={t(`${k}.editor.tags_placeholder`)}
                        className={inputCls}
                      />
                    </label>
                    <label className="flex flex-col gap-1.5 lg:col-span-2">
                      <span className="text-sm font-medium">{t(`${k}.editor.description`)}</span>
                      <input
                        type="text"
                        value={selected.description}
                        onChange={(e) => s.update({ description: e.target.value })}
                        placeholder={t(`${k}.editor.description_placeholder`)}
                        className={inputCls}
                      />
                    </label>
                  </div>

                  <div className="flex items-center gap-2 border-t border-border/60 px-5 sm:px-6">
                    <h2 className="flex h-12 min-w-0 flex-1 items-center text-sm font-medium">{t(`${k}.editor.content`)}</h2>
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
                      <button type="submit" className={solidBtn} disabled={s.refineLoading || !aiPrompt.trim()}>
                        {s.refineLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Wand2 className="h-3.5 w-3.5" aria-hidden />}
                        {s.refineLoading ? t(`${k}.ai.applying`) : t(`${k}.ai.apply`)}
                      </button>
                    </form>
                  )}

                  <div className="border-t border-border/60 p-4 sm:p-5">
                    <BlockMarkdownEditor
                      value={selected.content}
                      onChange={(v) => s.update({ content: v })}
                      height={520}
                      placeholder={t(`${k}.editor.content_placeholder`)}
                      allowTasks={false}
                    />
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
              guard(() => void runWizard());
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
              <button type="submit" className={solidBtn} disabled={s.wizardLoading || !wizardPrompt.trim()}>
                {s.wizardLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Wand2 className="h-3.5 w-3.5" aria-hidden />}
                {s.wizardLoading ? t(`${k}.wizard.generating`) : t(`${k}.wizard.generate`)}
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {deleteOpen && s.persistedName && (
        <DeleteDialog name={s.persistedName} busy={s.busy} ns={`${k}.delete`} t={t} onConfirm={remove} onClose={() => setDeleteOpen(false)} />
      )}

      {blockedBy && s.persistedName && (
        <Dialog title={t(`${k}.blocked.title`)} closeLabel={t(`${k}.blocked.close`)} onClose={() => setBlockedBy(null)}>
          <div className="flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">{t(`${k}.blocked.body`, { name: s.persistedName })}</p>
            <ul className="flex flex-col gap-1">
              {blockedBy.map((name) => (
                <li key={name} className="rounded-xl bg-secondary px-3 py-2 text-sm font-medium">
                  {name}
                </li>
              ))}
            </ul>
            <p className="text-sm text-muted-foreground">{t(`${k}.blocked.hint`)}</p>
            <div className="flex justify-end">
              <button type="button" className={solidBtn} autoFocus onClick={() => setBlockedBy(null)}>
                {t(`${k}.blocked.close`)}
              </button>
            </div>
          </div>
        </Dialog>
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

      <PageToast toast={s.toast} onDismiss={() => s.setToast(null)} />
    </div>
  );
}
