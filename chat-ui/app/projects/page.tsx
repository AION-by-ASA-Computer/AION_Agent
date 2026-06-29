"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Database, Plus, Settings2 } from "lucide-react";
import { SecondaryPageLayout } from "@/components/layout/SecondaryPageLayout";
import { ProjectCreateModal } from "@/components/memory/ProjectCreateModal";
import { ProjectSettingsModal } from "@/components/memory/ProjectSettingsModal";
import { fetchSqlProjects, type SqlProject } from "@/lib/api/query-memory";
import { fetchProfiles, type ProfileRow } from "@/lib/api/aion";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

function ProjectsPageInner() {
  const t = useT();
  const userId = useStoredUserId();
  const token = useStoredToken();
  const searchParams = useSearchParams();
  const initialProject = searchParams.get("project") ?? "";

  const [profiles, setProfiles] = useState<ProfileRow[]>([]);
  const [profileSlug, setProfileSlug] = useState("");
  const [projects, setProjects] = useState<SqlProject[]>([]);
  const [selected, setSelected] = useState(initialProject);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const loadProfiles = useCallback(async () => {
    if (!userId) return;
    const list = await fetchProfiles(userId, token);
    setProfiles(list);
    if (!profileSlug && list.length) {
      const pg = list.find((p) => p.name.toLowerCase().includes("postgres")) ?? list[0];
      setProfileSlug(pg.slug ?? pg.name.replace(/\s+/g, "_").toLowerCase());
    }
  }, [userId, token, profileSlug]);

  const loadProjects = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError(null);
    try {
      const list = await fetchSqlProjects(userId, token, profileSlug || undefined);
      setProjects(list);
      setSelected((prev) => {
        const fromUrl = initialProject && list.some((p) => p.slug === initialProject);
        if (fromUrl) return initialProject;
        if (prev && list.some((p) => p.slug === prev)) return prev;
        return list[0]?.slug ?? prev;
      });
    } catch (e) {
      setError(String(e));
      setProjects([]);
    } finally {
      setLoading(false);
    }
  }, [userId, token, profileSlug, initialProject]);

  useEffect(() => {
    void loadProfiles();
  }, [loadProfiles]);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (initialProject) setSelected(initialProject);
  }, [initialProject]);

  const current = projects.find((p) => p.slug === selected);

  return (
    <SecondaryPageLayout
      title={t("memory_project.page_title")}
      subtitle={t("memory_project.page_subtitle")}
      backHref="/"
      backLabel={t("memory_project.back_chat")}
    >
      <div className="-mx-2 max-w-5xl">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          {t("memory_project.profile_filter")}
          <select
            className="rounded-lg border border-border bg-background px-2 py-1.5 text-sm text-foreground"
            value={profileSlug}
            onChange={(e) => setProfileSlug(e.target.value)}
          >
            {profiles.map((p) => {
              const slug = p.slug ?? p.name.replace(/\s+/g, "_").toLowerCase();
              return (
                <option key={p.name} value={slug}>
                  {p.name}
                </option>
              );
            })}
          </select>
        </label>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
          onClick={() => setCreateOpen(true)}
        >
          <Plus size={16} />
          {t("memory_project.new_project")}
        </button>
      </div>

      {error ? <p className="mb-4 text-sm text-destructive">{error}</p> : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(220px,280px)_1fr]">
        <aside className="rounded-xl border border-border bg-card/50">
          <div className="border-b border-border px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {t("memory_project.label")}
          </div>
          {loading ? (
            <p className="p-4 text-sm text-muted-foreground">{t("memory_project.loading")}</p>
          ) : (
            <ul className="max-h-[60vh] overflow-y-auto p-1">
              {projects.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    className={cn(
                      "focus-ring flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm transition-colors",
                      selected === p.slug
                        ? "bg-primary/10 text-foreground"
                        : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                    )}
                    onClick={() => setSelected(p.slug)}
                  >
                    <Database size={14} className="shrink-0 text-primary" />
                    <span className="min-w-0 truncate font-medium">{p.display_name}</span>
                  </button>
                </li>
              ))}
              {projects.length === 0 ? (
                <li className="px-3 py-6 text-center text-xs text-muted-foreground">
                  {t("memory_project.no_projects")}
                </li>
              ) : null}
            </ul>
          )}
        </aside>

        <section className="rounded-xl border border-border bg-card/50 p-6">
          {current ? (
            <>
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">{current.display_name}</h2>
                  <p className="font-mono text-xs text-muted-foreground">{current.slug}</p>
                </div>
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted/50"
                  onClick={() => setSettingsOpen(true)}
                >
                  <Settings2 size={16} />
                  {t("memory_project.settings")}
                </button>
              </div>
              {current.description ? (
                <p className="mb-4 text-sm leading-relaxed text-muted-foreground">{current.description}</p>
              ) : (
                <p className="mb-4 text-sm italic text-muted-foreground">{t("memory_project.no_description")}</p>
              )}
              {current.role ? (
                <p className="text-sm text-muted-foreground">
                  {t("memory_project.your_role")}:{" "}
                  <span className="font-mono text-foreground">{current.role}</span>
                </p>
              ) : null}
              <p className="mt-6 text-xs text-muted-foreground">{t("memory_project.page_footer")}</p>
              <Link href="/" className="mt-2 inline-block text-sm text-primary hover:underline">
                {t("memory_project.back_chat")}
              </Link>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{t("memory_project.select_project")}</p>
          )}
        </section>
      </div>

      <ProjectCreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        userId={userId ?? ""}
        token={token}
        profileSlug={profileSlug || undefined}
        onCreated={(slug) => {
          setSelected(slug);
          void loadProjects();
        }}
      />
      <ProjectSettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        userId={userId ?? ""}
        token={token}
        profileSlug={profileSlug || undefined}
        projectSlug={selected}
        onUpdated={() => void loadProjects()}
      />
      </div>
    </SecondaryPageLayout>
  );
}

export default function ProjectsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">…</div>}>
      <ProjectsPageInner />
    </Suspense>
  );
}
