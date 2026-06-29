"use client";

import { useCallback, useEffect, useState } from "react";
import { Settings2, UserPlus, X } from "lucide-react";
import {
  fetchSqlProjectMembers,
  fetchSqlProjects,
  inviteSqlProjectMember,
  patchSqlProject,
  removeSqlProjectMember,
  type SqlProject,
  type SqlProjectMember,
} from "@/lib/api/query-memory";
import { useT } from "@/lib/i18n/use-t";
import Link from "next/link";

type Props = {
  open: boolean;
  onClose: () => void;
  userId: string;
  token?: string | null;
  profileSlug?: string;
  projectSlug: string;
  onUpdated?: () => void;
};

export function ProjectSettingsModal({
  open,
  onClose,
  userId,
  token,
  profileSlug,
  projectSlug,
  onUpdated,
}: Props) {
  const t = useT();
  const [project, setProject] = useState<SqlProject | null>(null);
  const [renameName, setRenameName] = useState("");
  const [renameDesc, setRenameDesc] = useState("");
  const [inviteId, setInviteId] = useState("");
  const [members, setMembers] = useState<SqlProjectMember[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"general" | "members">("general");

  const load = useCallback(async () => {
    if (!projectSlug) return;
    setError(null);
    try {
      const list = await fetchSqlProjects(userId, token, profileSlug);
      const cur = list.find((p) => p.slug === projectSlug) ?? null;
      setProject(cur);
      setRenameName(cur?.display_name ?? projectSlug);
      setRenameDesc(cur?.description ?? "");
      const m = await fetchSqlProjectMembers(userId, projectSlug, token);
      setMembers(m);
    } catch (e) {
      setError(String(e));
    }
  }, [userId, token, profileSlug, projectSlug]);

  useEffect(() => {
    if (open && projectSlug) void load();
  }, [open, projectSlug, load]);

  if (!open) return null;

  const onSaveGeneral = async () => {
    if (!projectSlug || !renameName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await patchSqlProject(
        userId,
        projectSlug,
        { display_name: renameName.trim(), description: renameDesc.trim() || "" },
        token
      );
      onUpdated?.();
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onInvite = async () => {
    if (!inviteId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await inviteSqlProjectMember(userId, projectSlug, inviteId.trim(), token);
      setInviteId("");
      await load();
      onUpdated?.();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onRemoveMember = async (identifier: string) => {
    if (!confirm(t("memory_project.remove_member_confirm"))) return;
    setBusy(true);
    try {
      await removeSqlProjectMember(userId, projectSlug, identifier, token);
      await load();
      onUpdated?.();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[220] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      role="presentation"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-settings-title"
        className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-border/60 bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border/60 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Settings2 size={20} aria-hidden />
            </div>
            <div>
              <h2 id="project-settings-title" className="text-base font-semibold">
                {t("memory_project.settings")}
              </h2>
              <p className="font-mono text-xs text-muted-foreground">{projectSlug}</p>
            </div>
          </div>
          <button type="button" className="rounded-lg p-1 text-muted-foreground hover:bg-muted" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="flex gap-1 border-b border-border/60 px-6 pt-2">
          {(["general", "members"] as const).map((id) => (
            <button
              key={id}
              type="button"
              className={`rounded-t-lg px-3 py-2 text-xs font-medium ${
                tab === id
                  ? "border border-b-0 border-border bg-background text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setTab(id)}
            >
              {id === "general" ? t("memory_project.tab_general") : t("memory_project.tab_members")}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {tab === "general" ? (
            <div className="space-y-3">
              <label className="block space-y-1">
                <span className="text-xs font-medium text-muted-foreground">{t("memory_project.rename")}</span>
                <input
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
                  value={renameName}
                  onChange={(e) => setRenameName(e.target.value)}
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-medium text-muted-foreground">{t("memory_project.desc_label")}</span>
                <textarea
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
                  rows={4}
                  value={renameDesc}
                  onChange={(e) => setRenameDesc(e.target.value)}
                />
              </label>
              {project?.role ? (
                <p className="text-xs text-muted-foreground">
                  {t("memory_project.your_role")}:{" "}
                  <span className="font-mono text-foreground">{project.role}</span>
                </p>
              ) : null}
              <button
                type="button"
                disabled={busy}
                className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground"
                onClick={() => void onSaveGeneral()}
              >
                {t("btn.save")}
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {project?.role === "owner" ? (
                <>
                  <label className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
                    <UserPlus size={14} />
                    {t("memory_project.invite")}
                  </label>
                  <div className="flex gap-2">
                    <input
                      className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm"
                      placeholder={t("memory_project.invite_placeholder")}
                      value={inviteId}
                      onChange={(e) => setInviteId(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && void onInvite()}
                    />
                    <button
                      type="button"
                      disabled={busy}
                      className="shrink-0 rounded-lg border border-border px-3 py-2 text-sm"
                      onClick={() => void onInvite()}
                    >
                      {t("memory_project.invite_btn")}
                    </button>
                  </div>
                </>
              ) : (
                <p className="text-xs text-muted-foreground">{t("memory_project.members_readonly")}</p>
              )}
              <ul className="divide-y divide-border rounded-lg border border-border">
                {members.map((m) => (
                  <li key={m.user_identifier} className="flex items-center gap-2 px-3 py-2 text-sm">
                    <span className="min-w-0 flex-1 truncate font-mono text-xs">{m.user_identifier}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">{m.role}</span>
                    {project?.role === "owner" && m.role !== "owner" ? (
                      <button
                        type="button"
                        className="text-xs text-destructive"
                        onClick={() => void onRemoveMember(m.user_identifier)}
                      >
                        {t("btn.delete")}
                      </button>
                    ) : null}
                  </li>
                ))}
                {members.length === 0 ? (
                  <li className="px-3 py-4 text-center text-xs text-muted-foreground">
                    {t("memory_project.no_members")}
                  </li>
                ) : null}
              </ul>
            </div>
          )}
          {error ? <p className="mt-3 text-xs text-destructive">{error}</p> : null}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-border/60 px-6 py-3">
          <Link
            href={`/projects?project=${encodeURIComponent(projectSlug)}`}
            className="text-xs text-primary hover:underline"
            onClick={onClose}
          >
            {t("memory_project.open_full_page")}
          </Link>
          <button type="button" className="rounded-lg border border-border px-4 py-2 text-sm" onClick={onClose}>
            {t("btn.cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}
