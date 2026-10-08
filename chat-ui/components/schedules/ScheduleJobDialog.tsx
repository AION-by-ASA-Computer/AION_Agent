"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  CalendarClock,
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  Database,
  MessageSquare,
  Search,
  Sparkles,
  Tag,
  X,
} from "lucide-react";

import { ComposerOptionRow } from "@/components/chat/ComposerOptionRow";
import { ProfileSelectorDropdown } from "@/components/chat/ProfileSelectorDropdown";
import { fetchSqlProjects, type SqlProject } from "@/lib/api/query-memory";
import {
  CronScheduleBuilder,
} from "@/components/schedules/CronScheduleBuilder";
import { AppSelect } from "@/components/ui/radix-select";
import {
  createCronJob,
  fetchProfiles,
  listCronJobRuns,
  patchCronJob,
  type ScheduledJobRow,
  type ScheduledRunRow,
} from "@/lib/api/aion";
import { isValidCronShape } from "@/lib/cron/schedule-builder";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

const COMMON_TIMEZONES = [
  "Europe/Rome",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "UTC",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Tokyo",
];

const PROMPT_TEMPLATES = ["briefing", "inbox", "weekly", "research"] as const;

/**
 * Floating label input component with smooth transition animation.
 * When unfocused and empty, the label acts as a placeholder.
 * When focused or containing text, the label floats to the top border.
 */
function FloatingInput({
  id,
  label,
  value,
  onChange,
  required,
  placeholder,
  className,
  isTitle = false,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  required?: boolean;
  placeholder?: string;
  className?: string;
  isTitle?: boolean;
}) {
  const [isFocused, setIsFocused] = useState(false);
  const isFloating = isFocused || Boolean(value);

  return (
    <div className="relative">
      <input
        id={id}
        value={value}
        onChange={onChange}
        onFocus={() => setIsFocused(true)}
        onBlur={() => setIsFocused(false)}
        required={required}
        placeholder={isFloating ? placeholder : ""}
        className={cn(
          "peer w-full rounded-2xl border border-input bg-background/80 transition-all duration-200 outline-none text-foreground",
          isTitle
            ? "px-4 pt-6 pb-2.5 text-base sm:text-lg font-semibold tracking-tight"
            : "px-4 pt-5 pb-2 text-sm",
          isFocused ? "border-primary ring-2 ring-primary/20" : "hover:border-border",
          className,
        )}
      />
      <label
        htmlFor={id}
        className={cn(
          "pointer-events-none absolute left-4 transition-all duration-200 select-none",
          isFloating
            ? cn(
              "top-1.5 font-semibold uppercase tracking-wider",
              isTitle
                ? "text-[10px] text-muted-foreground peer-focus:text-primary"
                : "text-[11px] text-primary",
            )
            : cn(
              "font-normal text-muted-foreground",
              isTitle ? "top-4 text-base" : "top-3.5 text-sm",
            ),
        )}
      >
        {label}
        {required ? <span className="ml-1 text-destructive">*</span> : null}
      </label>
    </div>
  );
}




/**
 * Modern Project Selector Dropdown styled consistently with ProfileSelectorDropdown.
 */
function ProjectSelectorDropdown({
  userId,
  token,
  profileSlug,
  value,
  onChange,
}: {
  userId: string;
  token?: string | null;
  profileSlug?: string;
  value: string;
  onChange: (slug: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [projects, setProjects] = useState<SqlProject[]>([]);
  const [loading, setLoading] = useState(true);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetchSqlProjects(userId, token, profileSlug)
      .then((list) => {
        if (!active) return;
        setProjects(list);
        if (list.length && (!value || !list.some((p) => p.slug === value))) {
          onChange(list[0].slug);
        }
      })
      .catch(() => {
        if (active) setProjects([]);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [userId, token, profileSlug, value, onChange]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [open]);

  const selectedProject = projects.find((p) => p.slug === value);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter(
      (p) =>
        p.display_name.toLowerCase().includes(q) ||
        p.slug.toLowerCase().includes(q) ||
        (p.description && p.description.toLowerCase().includes(q)),
    );
  }, [projects, search]);

  return (
    <div ref={dropdownRef} className={cn("relative", open && "z-40")}>
      <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Memoria & Conoscenza
      </label>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center justify-between gap-3 rounded-2xl border border-input bg-background/80 px-3.5 py-2.5 text-left transition hover:border-primary/50 focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none cursor-pointer",
          open && "border-primary ring-2 ring-primary/20",
        )}
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-rose-500/10 text-rose-500 dark:text-rose-400">
            <Database className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-foreground truncate">
              {loading
                ? "Caricamento progetti…"
                : selectedProject?.display_name || value || "Nessun progetto selezionato"}
            </div>
            <div className="text-xs text-muted-foreground truncate">
              {selectedProject?.description || (selectedProject?.slug === "default" ? "Progetto QueryMemory predefinito" : "Spazio di memoria SQL dedicato")}
            </div>
          </div>
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform duration-200 shrink-0",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="absolute top-full left-0 z-[60] mt-1.5 w-full rounded-2xl border border-border bg-popover text-popover-foreground dark:bg-zinc-900 p-2.5 shadow-2xl animate-in fade-in-0 zoom-in-95 duration-150">
          <div className="flex items-center justify-between border-b border-border/40 pb-2 px-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Seleziona Progetto Memoria
            </span>
            <span className="text-[11px] text-muted-foreground font-medium">
              {filtered.length} {filtered.length === 1 ? "progetto" : "progetti"}
            </span>
          </div>

          {projects.length > 3 && (
            <div className="relative my-2">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Cerca progetto memoria…"
                className="w-full rounded-xl border border-input bg-muted/40 pl-8 pr-7 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:border-primary focus:bg-background focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground text-xs p-0.5 rounded-full"
                >
                  ✕
                </button>
              )}
            </div>
          )}

          <div className="mt-1 max-h-56 overflow-y-auto space-y-1 custom-scrollbar p-0.5">
            {filtered.map((proj) => {
              const isSelected = proj.slug === value;
              return (
                <button
                  key={proj.id || proj.slug}
                  type="button"
                  onClick={() => {
                    onChange(proj.slug);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center justify-between gap-2.5 rounded-xl border p-2 text-left transition cursor-pointer",
                    isSelected
                      ? "border-primary/50 bg-primary/10 text-primary shadow-xs"
                      : "border-transparent hover:bg-muted/60 text-foreground",
                  )}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div
                      className={cn(
                        "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-xs font-bold transition-colors",
                        isSelected
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground",
                      )}
                    >
                      <Database className="h-3.5 w-3.5" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-foreground truncate">
                        {proj.display_name}
                      </div>
                      {proj.description ? (
                        <div className="text-[11px] text-muted-foreground truncate max-w-sm">
                          {proj.description}
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {isSelected && <Check className="h-4 w-4 shrink-0 text-primary ml-2" />}
                </button>
              );
            })}
            {filtered.length === 0 && (
              <div className="py-4 text-center text-xs text-muted-foreground">
                Nessun progetto trovato
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function ScheduleJobDialog({
  mode,
  job,
  userId,
  token,
  initialName,
  initialPrompt,
  onClose,
}: {
  mode: "create" | "edit";
  job: ScheduledJobRow | null;
  userId: string;
  token: string | null;
  initialName?: string;
  initialPrompt?: string;
  onClose: () => void;
}) {
  const t = useT();
  const [profiles, setProfiles] = useState<
    Array<{ name: string; slug: string; description?: string }>
  >([]);
  const [name, setName] = useState(job?.name ?? initialName ?? "");
  const [cron, setCron] = useState(job?.cron_expression ?? "0 9 * * *");
  const [prompt, setPrompt] = useState(job?.prompt ?? initialPrompt ?? "");
  const [profile, setProfile] = useState(job?.profile_slug ?? "generic_assistant");
  const [sessionMode, setSessionMode] = useState<"fixed" | "new">(
    (job?.session_mode as "fixed" | "new") ?? "fixed",
  );
  const [timezone, setTimezone] = useState(job?.timezone ?? "Europe/Rome");
  const [sqlProject, setSqlProject] = useState(job?.sql_query_project ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sqlProjectPayload =
    (sqlProject || "").trim().toLowerCase() === "default"
      ? null
      : (sqlProject || "").trim() || null;

  useEffect(() => {
    if (!userId) return;
    void fetchProfiles(userId, token).then((rows) => {
      const mapped = rows.map((row) => ({
        name: row.name,
        slug: (row as { slug?: string }).slug || row.name,
        description: row.description,
      }));
      setProfiles(mapped);
      if (!job && mapped[0]?.slug) setProfile(mapped[0].slug);
    });
  }, [userId, token, job]);

  const tzItems = COMMON_TIMEZONES.map((tz) => ({ value: tz, label: tz }));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!userId || !name.trim() || !prompt.trim()) {
      setError(t("schedulesPage.form_required"));
      return;
    }
    if (!isValidCronShape(cron)) {
      setError(t("schedulesPage.cron.invalid"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (mode === "create") {
        const created = await createCronJob(
          userId,
          {
            name: name.trim(),
            cron_expression: cron,
            prompt: prompt.trim(),
            profile_slug: profile,
            session_mode: sessionMode,
            sql_query_project: sqlProjectPayload,
            timezone,
            enabled: true,
          },
          token,
        );
        if (!created) throw new Error(t("schedulesPage.save_error"));
      } else if (job) {
        const updated = await patchCronJob(
          userId,
          job.job_id,
          {
            name: name.trim(),
            cron_expression: cron,
            prompt: prompt.trim(),
            profile_slug: profile,
            session_mode: sessionMode,
            sql_query_project: sqlProjectPayload,
            timezone,
          },
          token,
        );
        if (!updated) throw new Error(t("schedulesPage.save_error"));
      }
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("schedulesPage.save_error"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 sm:p-6 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="max-h-[92vh] w-full max-w-2xl flex flex-col rounded-3xl border border-border bg-card text-card-foreground shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
        {/* Header Modale */}
        <div className="flex items-center justify-between border-b border-border p-5 sm:p-6 bg-muted/20 shrink-0">
          <div className="flex items-center gap-3.5 min-w-0 pr-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-primary/25 bg-primary/10 text-primary shadow-sm">
              <CalendarClock className="h-5 w-5" aria-hidden />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg sm:text-xl font-bold tracking-tight text-foreground truncate">
                {mode === "create" ? t("schedulesPage.create_title") : t("schedulesPage.edit_title")}
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {t("schedulesPage.dialog_subtitle")}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl p-2 text-muted-foreground hover:bg-muted hover:text-foreground transition cursor-pointer shrink-0"
            aria-label={t("schedulesPage.cancel")}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Form Container */}
        <form onSubmit={(e) => void save(e)} className="flex flex-col flex-1 min-h-0 overflow-hidden bg-card">
          {/* Form Body Scrollabile */}
          <div className="flex-1 overflow-y-auto p-5 sm:p-6 space-y-6">
            {/* 1. Nome dell'automazione */}
            <div>
              <FloatingInput
                id="schedule-name"
                label={t("schedulesPage.field_name")}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Es: Briefing Mattutino Report"
                isTitle
                required
              />
            </div>

            {/* 2. Pianificazione & Frequenza */}
            <div className="rounded-2xl border border-border/70 bg-muted/25 p-4 space-y-4 shadow-xs">
              <div className="flex items-center gap-2 border-b border-border/40 pb-2">
                <Clock className="h-4 w-4 text-primary" />
                <span className="text-xs font-semibold uppercase tracking-wide text-foreground">
                  {t("schedulesPage.schedule_label")}
                </span>
              </div>

              <div>
                <CronScheduleBuilder
                  key={job?.job_id ?? "new"}
                  initialValue={job?.cron_expression ?? cron}
                  onChange={setCron}
                  timezone={timezone}
                />
              </div>

              <div className="pt-2 border-t border-border/50">
                <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t("schedulesPage.field_timezone")}
                </label>
                <AppSelect
                  value={timezone}
                  onValueChange={setTimezone}
                  items={tzItems}
                  triggerClassName="w-full max-w-none"
                />
              </div>
            </div>

            {/* 3. Profilo Agente AI */}
            {profiles.length > 0 && (
              <div>
                <ProfileSelectorDropdown
                  profiles={profiles}
                  value={profile}
                  onChange={setProfile}
                />
              </div>
            )}

            {/* 4. Memoria & Conoscenza */}
            <div className="space-y-1.5">
              <ProjectSelectorDropdown
                userId={userId}
                token={token}
                profileSlug={profile}
                value={sqlProject || ""}
                onChange={setSqlProject}
              />
              <p className="px-1 text-[11px] text-muted-foreground leading-relaxed">
                {t("schedulesPage.field_sql_project_hint")}
              </p>
            </div>

            {/* 5. Istruzioni / Prompt */}
            <div className="space-y-2.5">
              <div className="flex items-center justify-between pb-1">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-primary" />
                  <span className="text-xs font-semibold uppercase tracking-wide text-foreground">
                    {t("schedulesPage.field_prompt")}
                  </span>
                </div>
                <span className="text-[11px] text-muted-foreground font-medium">
                  {t("schedulesPage.prompt_templates")}
                </span>
              </div>

              {/* Template rapidi */}
              <div className="flex flex-wrap gap-1.5">
                {PROMPT_TEMPLATES.map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => {
                      setPrompt(t(`schedulesPage.templates.${key}.prompt`));
                      if (!name.trim()) setName(t(`schedulesPage.templates.${key}.name`));
                    }}
                    className="rounded-full border border-border/80 bg-muted/40 px-3 py-1 text-xs font-medium text-muted-foreground transition hover:border-primary/50 hover:bg-primary/10 hover:text-primary cursor-pointer"
                  >
                    {t(`schedulesPage.templates.${key}.name`)}
                  </button>
                ))}
              </div>

              <textarea
                id="schedule-prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                required
                rows={4}
                placeholder={t("schedulesPage.prompt_placeholder") || "Descrivi l'istruzione o la query da eseguire periodicamente..."}
                className="w-full rounded-2xl border border-input bg-background/80 p-3.5 text-sm leading-relaxed text-foreground placeholder:text-muted-foreground/60 transition-all duration-200 outline-none resize-y hover:border-border focus:border-primary focus:ring-2 focus:ring-primary/20"
              />
            </div>

            {/* 6. Conversazione */}
            <fieldset className="space-y-2 rounded-2xl border border-border/70 bg-muted/25 p-3.5 shadow-xs">
              <legend className="flex items-center gap-1.5 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <MessageSquare className="h-3.5 w-3.5 text-primary" />
                <span>{t("schedulesPage.session_legend")}</span>
              </legend>
              <ComposerOptionRow
                label={t("schedulesPage.session_fixed")}
                description={t("schedulesPage.session_fixed_desc")}
                selected={sessionMode === "fixed"}
                onClick={() => setSessionMode("fixed")}
              />
              <ComposerOptionRow
                label={t("schedulesPage.session_new")}
                description={t("schedulesPage.session_new_desc")}
                selected={sessionMode === "new"}
                onClick={() => setSessionMode("new")}
              />
            </fieldset>

            {/* Messaggio di Errore */}
            {error ? (
              <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs font-semibold text-red-500">
                {error}
              </div>
            ) : null}

          </div>

          {/* Footer Fisso */}
          <div className="border-t border-border p-4 sm:px-6 bg-muted/20 flex items-center justify-end gap-3 shrink-0">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-border px-4 py-2 text-xs font-semibold text-foreground hover:bg-muted transition cursor-pointer"
            >
              {t("schedulesPage.cancel")}
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-xl bg-primary px-5 py-2 text-xs font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 transition cursor-pointer disabled:opacity-50"
            >
              {saving
                ? t("schedulesPage.saving")
                : mode === "create"
                  ? t("schedulesPage.create")
                  : t("schedulesPage.save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/**
 * ScheduleJobRuns: Displays recent job executions.
 * By default, only the single latest execution is shown.
 * A button allows expanding to view up to the last 8 executions.
 */
export function ScheduleJobRuns({
  jobId,
  userId,
  token,
  expanded: controlledExpanded,
  onToggleExpand,
}: {
  jobId: string;
  userId: string;
  token: string | null;
  expanded?: boolean;
  onToggleExpand?: () => void;
}) {
  const t = useT();
  const [runs, setRuns] = useState<ScheduledRunRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [localExpanded, setLocalExpanded] = useState(false);
  const isExpanded = controlledExpanded !== undefined ? controlledExpanded : localExpanded;
  const toggleExpanded = onToggleExpand ?? (() => setLocalExpanded((v) => !v));

  const loadRuns = useCallback(async () => {
    try {
      const rows = await listCronJobRuns(userId, jobId, token);
      setRuns(rows.slice(0, 8));
    } catch {
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, [userId, jobId, token]);

  useEffect(() => {
    setLoading(true);
    void loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    if (!runs.some((r) => r.status === "running")) return;
    const timer = setInterval(() => void loadRuns(), 2000);
    return () => clearInterval(timer);
  }, [runs, loadRuns]);

  function renderRunItem(run: ScheduledRunRow) {
    const chatId = run.conversation_id || run.session_id;
    const when = run.started_at ? new Date(run.started_at).toLocaleString() : "";
    const statusClass =
      run.status === "success"
        ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
        : run.status === "error"
          ? "bg-destructive/15 text-destructive"
          : run.status === "running"
            ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
            : "bg-muted text-muted-foreground";

    return (
      <div
        key={run.run_id}
        className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border/50 bg-card p-2.5 text-xs shadow-2xs"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-bold uppercase", statusClass)}>
              {run.status === "success" ? "Completata" : run.status === "error" ? "Errore" : run.status}
            </span>
            <span className="text-muted-foreground text-[11px]">{when}</span>
          </div>
          {run.error_message ? (
            <p className="mt-1 line-clamp-2 text-[11px] text-destructive leading-relaxed">
              {run.error_message}
            </p>
          ) : null}
          {run.assistant_preview && !run.error_message ? (
            <p className="mt-1 line-clamp-1 text-[11px] text-muted-foreground leading-relaxed">
              {run.assistant_preview}
            </p>
          ) : null}
        </div>
        {chatId ? (
          <Link
            href={`/c/${chatId}`}
            className="shrink-0 rounded-lg border border-border bg-background px-2.5 py-1 text-[11px] font-semibold text-primary hover:bg-muted transition"
          >
            {t("schedulesPage.open_run_chat")}
          </Link>
        ) : null}
      </div>
    );
  }

  return (
    <div className="border-t border-border/50 bg-muted/20 px-4 py-3 sm:px-5">
      <div className="flex items-center justify-between gap-2 mb-2">
        <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
          {t("schedulesPage.recent_runs")}
        </p>
        {runs.length > 1 && (
          <button
            type="button"
            onClick={toggleExpanded}
            className="inline-flex items-center gap-1 text-[11px] font-semibold text-primary hover:underline cursor-pointer"
          >
            {isExpanded ? (
              <>
                <ChevronUp className="h-3 w-3" />
                <span>Mostra solo ultima</span>
              </>
            ) : (
              <>
                <ChevronDown className="h-3 w-3" />
                <span>Altre esecuzioni</span>
              </>
            )}
          </button>
        )}
      </div>

      {loading ? (
        <p className="text-xs text-muted-foreground">{t("schedulesPage.runs_loading")}</p>
      ) : runs.length === 0 ? (
        <p className="text-xs text-muted-foreground italic">{t("schedulesPage.runs_empty")}</p>
      ) : (
        <div className="space-y-1.5">
          {/* Mostra sempre l'ultima esecuzione */}
          {renderRunItem(runs[0])}

          {/* Se espanso, mostra le altre fino a 8 */}
          {isExpanded && runs.length > 1 && (
            <div className="space-y-1.5 pt-1 animate-in fade-in duration-200">
              {runs.slice(1, 8).map(renderRunItem)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
