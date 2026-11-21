"use client";

import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "@/lib/api/headers";
import { useT } from "@/lib/i18n/use-t";
import { getLocale } from "@/lib/i18n/i18n-store";
import {
  Folder,
  FolderPlus,
  Users,
  UserPlus,
  UserMinus,
  Trash2,
  Edit2,
  Loader2,
  CheckCircle,
  Shield,
  Calendar,
  User,
  Plus,
  Eye,
  Save,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { apiBase } from "@/lib/api";
import { PageToast, type ToastState } from "@/components/PageToast";
import { Dialog } from "@/components/profiles/Dialog";
import { Select } from "@/components/ui/Select";
import { DeleteDialog } from "@/components/ui/ConfirmDialogs";
import { ghostBtn, inputCls, outlineBtn, solidBtn, dangerBtn } from "@/components/ui/classes";

interface ProjectMember {
  user_identifier: string;
  role: string;
  invited_by?: string;
  created_at: string;
}

interface Project {
  id: number;
  tenant_id: string;
  slug: string;
  display_name: string;
  description?: string;
  datasource_key: string;
  profile_slug?: string;
  scope_mode: string;
  created_by?: string;
  created_at: string;
  members: ProjectMember[];
}

function hueOf(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) % 360;
  return h;
}

interface ProfileRow {
  name: string;
  slug?: string;
}

interface UserRow {
  id: string;
  identifier?: string;
  display_name?: string;
  email?: string;
  account_type?: string;
}

export default function MemoryPage() {
  const t = useT();
  const [toast, setToast] = useState<ToastState>(null);
  const show = useCallback((message: string, variant: "success" | "error" = "success") => {
    setToast({ message, variant });
  }, []);

  const [projects, setProjects] = useState<Project[]>([]);
  const [profiles, setProfiles] = useState<ProfileRow[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(false);

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const [projectDetails, setProjectDetails] = useState<Project | null>(null);
  const [isEditingDetails, setIsEditingDetails] = useState(false);
  const [detailsTab, setDetailsTab] = useState<"overview" | "members">("overview");

  const [isDeleteProjOpen, setIsDeleteProjOpen] = useState(false);
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null);
  const [isDeleteMemberOpen, setIsDeleteMemberOpen] = useState(false);
  const [memberToDelete, setMemberToDelete] = useState<{ projectSlug: string; userIdentifier: string } | null>(null);

  const [createSlug, setCreateSlug] = useState("");
  const [createDisplayName, setCreateDisplayName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [createProfileSlug, setCreateProfileSlug] = useState("");
  const [createScopeMode, setCreateScopeMode] = useState("inherit");

  const [editDisplayName, setEditDisplayName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editProfileSlug, setEditProfileSlug] = useState("");

  const [memberUserIdentifier, setMemberUserIdentifier] = useState("");
  const [memberRole, setMemberRole] = useState("member");

  const fetchProfiles = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles`);
      if (res.ok) {
        const data = await res.json();
        setProfiles(Array.isArray(data) ? data : []);
      }
    } catch (e) {
      console.error("Profiles fetch error", e);
    }
  }, []);

  const fetchUsers = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/users?include_service=1`);
      if (res.ok) {
        const data = await res.json();
        setUsers(Array.isArray(data?.users) ? data.users : []);
      }
    } catch (e) {
      console.error("Users fetch error", e);
    }
  }, []);

  const fetchProjects = useCallback(async (opts?: { notify?: boolean }) => {
    const notify = opts?.notify !== false;
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/query-memory/projects`);
      if (!res.ok) {
        show(t("admin_memory.toast.fetch_http_error", { status: res.status }), "error");
        return;
      }
      const data = await res.json();
      const projectList = Array.isArray(data) ? data : [];
      setProjects(projectList);
      setProjectDetails((prevDetails) => {
        if (!prevDetails) return null;
        const updated = projectList.find((p: Project) => p.slug === prevDetails.slug);
        return updated || null;
      });
      if (notify) show(t("admin_memory.toast.list_updated"));
    } catch (e) {
      show(t("admin_memory.toast.load_error", { error: String(e) }), "error");
    } finally {
      setLoading(false);
    }
  }, [show, t]);

  const loadAllData = useCallback(() => {
    void fetchProfiles();
    void fetchUsers();
    void fetchProjects({ notify: false });
  }, [fetchProfiles, fetchUsers, fetchProjects]);

  useEffect(() => {
    loadAllData();
  }, [loadAllData]);

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createSlug.trim() || !createDisplayName.trim()) {
      show(t("admin_memory.toast.slug_name_required"), "error");
      return;
    }
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/query-memory/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          slug: createSlug.trim(),
          display_name: createDisplayName.trim(),
          description: createDescription.trim() || null,
          profile_slug: createProfileSlug || null,
          scope_mode: createScopeMode,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        show(err.detail || t("admin_memory.toast.http_error", { status: res.status }), "error");
      } else {
        show(t("admin_memory.toast.project_created", { name: createDisplayName }));
        setIsCreateOpen(false);
        setCreateSlug("");
        setCreateDisplayName("");
        setCreateDescription("");
        setCreateProfileSlug("");
        setCreateScopeMode("inherit");
        void fetchProjects({ notify: false });
      }
    } catch (e) {
      show(String(e), "error");
    } finally {
      setLoading(false);
    }
  };

  const handleEditProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!projectDetails) return;
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/query-memory/projects/${projectDetails.slug}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: editDisplayName.trim(),
          description: editDescription.trim() || null,
          profile_slug: editProfileSlug || null,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        show(err.detail || t("admin_memory.toast.http_error", { status: res.status }), "error");
      } else {
        show(t("admin_memory.toast.project_updated", { name: editDisplayName }));
        setIsEditingDetails(false);
        void fetchProjects({ notify: false });
      }
    } catch (e) {
      show(String(e), "error");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteProject = async () => {
    if (!projectToDelete) return;
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/query-memory/projects/${projectToDelete.slug}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        show(t("admin_memory.toast.delete_failed", { status: res.status }), "error");
      } else {
        show(t("admin_memory.toast.project_deleted", { name: projectToDelete.display_name }));
        setIsDeleteProjOpen(false);
        setProjectToDelete(null);
        setIsDetailsOpen(false);
        setProjectDetails(null);
        setIsEditingDetails(false);
        void fetchProjects({ notify: false });
      }
    } catch (e) {
      show(String(e), "error");
    } finally {
      setLoading(false);
    }
  };

  const handleAddMember = async (e: React.FormEvent, projectSlug: string) => {
    e.preventDefault();
    if (!memberUserIdentifier.trim()) {
      show(t("admin_memory.toast.user_required"), "error");
      return;
    }
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/query-memory/projects/${projectSlug}/members`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_identifier: memberUserIdentifier.trim(),
          role: memberRole,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        show(err.detail || t("admin_memory.toast.http_error", { status: res.status }), "error");
      } else {
        show(t("admin_memory.toast.member_added", { user: memberUserIdentifier }));
        setMemberUserIdentifier("");
        setMemberRole("member");
        void fetchProjects({ notify: false });
      }
    } catch (e) {
      show(String(e), "error");
    } finally {
      setLoading(false);
    }
  };

  const handleRemoveMember = async () => {
    if (!memberToDelete) return;
    setLoading(true);
    try {
      const { projectSlug, userIdentifier } = memberToDelete;
      const res = await apiFetch(
        `${apiBase()}/admin/query-memory/projects/${projectSlug}/members/${encodeURIComponent(userIdentifier)}`,
        { method: "DELETE" }
      );
      if (!res.ok) {
        show(t("admin_memory.toast.revoke_failed", { status: res.status }), "error");
      } else {
        show(t("admin_memory.toast.member_revoked", { user: userIdentifier }));
        setIsDeleteMemberOpen(false);
        setMemberToDelete(null);
        void fetchProjects({ notify: false });
      }
    } catch (e) {
      show(String(e), "error");
    } finally {
      setLoading(false);
    }
  };

  const openDetailsModal = (p: Project) => {
    setProjectDetails(p);
    setEditDisplayName(p.display_name);
    setEditDescription(p.description || "");
    setEditProfileSlug(p.profile_slug || "");
    setMemberUserIdentifier("");
    setMemberRole("member");
    setIsEditingDetails(false);
    setDetailsTab("overview");
    setIsDetailsOpen(true);
  };

  const closeDetails = () => {
    setIsDetailsOpen(false);
    setProjectDetails(null);
    setIsEditingDetails(false);
  };

  const formatDate = (isoString: string) => {
    try {
      return new Date(isoString).toLocaleDateString(getLocale(), {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return isoString;
    }
  };

  const roleOptions = [
    { value: "member", label: t("admin_memory.roles.member"), description: t("admin_memory.roles.member_desc") },
    { value: "owner", label: t("admin_memory.roles.owner"), description: t("admin_memory.roles.owner_desc") },
  ];

  const scopeOptions = [
    { value: "inherit", label: t("admin_memory.scopes.inherit"), description: t("admin_memory.scopes.inherit_desc") },
    { value: "shared", label: t("admin_memory.scopes.shared"), description: t("admin_memory.scopes.shared_desc") },
    { value: "per_user", label: t("admin_memory.scopes.per_user"), description: t("admin_memory.scopes.per_user_desc") },
  ];

  const scopeLabels: Record<string, string> = Object.fromEntries(scopeOptions.map((o) => [o.value, o.label]));

  const profileOptions = [
    { value: "", label: t("admin_memory.no_profile") },
    ...profiles.map((p) => ({ value: p.slug || p.name.replace(/\s+/g, "_").toLowerCase(), label: p.name })),
  ];

  const existingMemberIds = new Set(
    (projectDetails?.members ?? []).map((m) => m.user_identifier.toLowerCase()),
  );
  const userOptions = users
    .filter((u) => {
      const id = u.identifier || u.id;
      return Boolean(id) && !existingMemberIds.has(id.toLowerCase());
    })
    .map((u) => {
      const value = u.identifier || u.id;
      const label = u.display_name ? `${u.display_name} (${value})` : value;
      const parts = [
        u.email && u.email !== value ? u.email : null,
        u.account_type === "service" ? t("admin_memory.service_account") : null,
      ].filter(Boolean);
      return {
        value,
        label,
        description: parts.length > 0 ? parts.join(" · ") : undefined,
      };
    });

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <PageToast toast={toast} onDismiss={() => setToast(null)} />

      {/* Page header */}
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">
            {t("admin_memory.title")}
          </h1>
          <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">
            {t("admin_memory.subtitle")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className={solidBtn}
            onClick={() => setIsCreateOpen(true)}
          >
            <FolderPlus className="h-4 w-4" aria-hidden />
            {t("admin_memory.new_project")}
          </button>
        </div>
      </header>

      {/* Projects list */}
      <section className="flex flex-col gap-4" aria-label={t("admin_memory.active_projects_aria")}>
        {!loading && projects.length === 0 ? (
          <div className="flex flex-col items-center rounded-3xl border border-dashed border-border px-6 py-20 text-center">
            <Folder className="mb-4 h-8 w-8 text-muted-foreground" strokeWidth={1.5} aria-hidden />
            <h2 className="text-lg font-semibold tracking-[-0.015em]">{t("admin_memory.empty.title")}</h2>
            <p className="mt-1.5 max-w-[46ch] text-sm text-muted-foreground">
              {t("admin_memory.empty.description")}
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              <button type="button" className={solidBtn} onClick={() => setIsCreateOpen(true)}>
                <Plus className="h-4 w-4" aria-hidden />
                {t("admin_memory.new_project")}
              </button>
            </div>
          </div>
        ) : (
          <div className="overflow-hidden rounded-3xl border border-border/70 bg-card">
            {loading && projects.length === 0 ? (
              <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground" role="status">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                {t("admin_memory.loading")}
              </div>
            ) : (
              <table className="w-full text-left" role="grid">
                <thead>
                  <tr className="border-b border-border/60 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    <th className="px-5 py-3.5" scope="col">{t("admin_memory.table.project")}</th>
                    <th className="px-5 py-3.5" scope="col">{t("admin_memory.table.profile")}</th>
                    <th className="px-5 py-3.5" scope="col">{t("admin_memory.table.scope")}</th>
                    <th className="px-5 py-3.5" scope="col">{t("admin_memory.table.members")}</th>
                    <th className="px-5 py-3.5" scope="col">{t("admin_memory.table.created")}</th>
                    <th className="px-5 py-3.5 text-right" scope="col">{t("admin_memory.table.actions")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/40 text-sm">
                  {projects.map((project) => (
                    <tr
                      key={project.id}
                      className="cursor-pointer transition-colors hover:bg-secondary/40"
                      onClick={() => openDetailsModal(project)}
                    >
                      <td className="px-5 py-4">
                        <div className="font-medium text-foreground">{project.display_name}</div>
                        <div className="mt-0.5 font-mono text-xs text-muted-foreground">{project.slug}</div>
                      </td>
                      <td className="px-5 py-4">
                        {project.profile_slug ? (
                          <span className="rounded-lg border border-border bg-secondary px-2 py-0.5 font-mono text-xs font-medium">
                            {project.profile_slug}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="px-5 py-4">
                        <span className="rounded-lg border border-border bg-secondary px-2 py-0.5 font-mono text-xs font-medium uppercase tracking-wide">
                          {scopeLabels[project.scope_mode] ?? project.scope_mode}
                        </span>
                      </td>
                      <td className="px-5 py-4">
                        <span className="inline-flex items-center gap-1.5 text-sm tabular-nums">
                          <Users className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                          {project.members?.length || 0}
                        </span>
                      </td>
                      <td className="px-5 py-4 text-xs text-muted-foreground tabular-nums">
                        {formatDate(project.created_at)}
                      </td>
                      <td
                        className="px-5 py-4 text-right"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="inline-flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => openDetailsModal(project)}
                            title={t("admin_memory.actions.view_details")}
                            className={ghostBtn}
                          >
                            <Eye className="h-4 w-4" aria-hidden />
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setProjectToDelete(project);
                              setIsDeleteProjOpen(true);
                            }}
                            title={t("admin_memory.actions.delete_project")}
                            className={cn(ghostBtn, "hover:text-destructive")}
                          >
                            <Trash2 className="h-4 w-4" aria-hidden />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </section>

      {/* MODAL: Project details & members */}
      {isDetailsOpen && projectDetails && (
        <Dialog
          title={isEditingDetails ? t("admin_memory.details.edit_title") : projectDetails.display_name}
          closeLabel={t("admin_memory.common.close")}
          onClose={closeDetails}
          className="max-w-2xl"
        >
          <div className="flex flex-col gap-5">
            <p className="-mt-1 font-mono text-xs text-muted-foreground">{projectDetails.slug}</p>

            <div role="tablist" aria-label={t("admin_memory.details.sections_aria")} className="flex gap-1 border-b border-border">
              {(["overview", "members"] as const).map((id) => {
                const active = detailsTab === id;
                return (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setDetailsTab(id)}
                    className={cn(
                      "focus-ring -mb-px flex items-center gap-2 border-b-2 px-3 pb-2.5 pt-1 text-sm font-medium transition-colors",
                      active ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {id === "overview" ? t("admin_memory.details.tab_overview") : t("admin_memory.details.tab_members")}
                    {id === "members" && (
                      <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">
                        {projectDetails.members?.length || 0}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>

            <div className="max-h-[56vh] overflow-y-auto pr-1" role="tabpanel">
              {detailsTab === "overview" &&
                (isEditingDetails ? (
                  <form onSubmit={handleEditProject} className="flex flex-col gap-4">
                    <label className="flex flex-col gap-1.5">
                      <span className="text-sm font-medium">{t("admin_memory.fields.display_name")}</span>
                      <input required autoFocus value={editDisplayName} onChange={(e) => setEditDisplayName(e.target.value)} className={inputCls} />
                    </label>
                    <label className="flex flex-col gap-1.5">
                      <span className="text-sm font-medium">{t("admin_memory.fields.description")}</span>
                      <textarea value={editDescription} onChange={(e) => setEditDescription(e.target.value)} rows={3} className={cn(inputCls, "resize-none")} />
                    </label>
                    <label className="flex flex-col gap-1.5">
                      <span className="text-sm font-medium">{t("admin_memory.fields.linked_profile")}</span>
                      <Select value={editProfileSlug} onChange={setEditProfileSlug} options={profileOptions} />
                    </label>
                    <div className="flex justify-end gap-2 pt-1">
                      <button type="button" onClick={() => setIsEditingDetails(false)} className={ghostBtn}>
                        {t("admin_memory.common.cancel")}
                      </button>
                      <button type="submit" disabled={loading} className={solidBtn}>
                        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
                        {t("admin_memory.details.save_changes")}
                      </button>
                    </div>
                  </form>
                ) : (
                  <div className="flex flex-col gap-5">
                    <p className={cn("text-sm leading-relaxed", projectDetails.description ? "text-foreground" : "text-muted-foreground")}>
                      {projectDetails.description || t("admin_memory.details.no_description")}
                    </p>

                    <dl className="grid gap-x-6 gap-y-3 rounded-2xl border border-border/70 p-4 text-sm sm:grid-cols-2">
                      {[
                        {
                          icon: Shield,
                          label: t("admin_memory.details.source_db"),
                          value: projectDetails.datasource_key.startsWith("default:")
                            ? t("admin_memory.details.not_configured")
                            : projectDetails.datasource_key,
                          mono: !projectDetails.datasource_key.startsWith("default:"),
                          hint: projectDetails.datasource_key.startsWith("default:")
                            ? t("admin_memory.details.source_db_missing_hint")
                            : t("admin_memory.details.source_db_hint"),
                        },
                        { icon: Users, label: t("admin_memory.table.scope"), value: scopeLabels[projectDetails.scope_mode] ?? projectDetails.scope_mode },
                        {
                          icon: CheckCircle,
                          label: t("admin_memory.fields.linked_profile"),
                          value: projectDetails.profile_slug || t("admin_memory.details.none"),
                          mono: Boolean(projectDetails.profile_slug),
                        },
                        { icon: User, label: t("admin_memory.details.created_by"), value: projectDetails.created_by || t("admin_memory.common.system") },
                        { icon: Calendar, label: t("admin_memory.table.created"), value: formatDate(projectDetails.created_at) },
                      ].map(({ icon: Icon, label, value, mono, hint }) => (
                        <div key={label} className="flex min-w-0 flex-col gap-0.5">
                          <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <Icon className="h-3.5 w-3.5" aria-hidden />
                            {label}
                          </dt>
                          <dd className={cn("truncate", mono && "font-mono text-[13px]")} title={hint ?? value}>
                            {value}
                          </dd>
                        </div>
                      ))}
                    </dl>

                    <div className="flex flex-wrap items-center gap-2 border-t border-border/60 pt-4">
                      <button
                        type="button"
                        onClick={() => {
                          setProjectToDelete(projectDetails);
                          setIsDeleteProjOpen(true);
                        }}
                        className={cn(ghostBtn, "hover:text-destructive")}
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                        {t("admin_memory.actions.delete_project")}
                      </button>
                      <button type="button" onClick={() => setIsEditingDetails(true)} className={cn(outlineBtn, "ml-auto")}>
                        <Edit2 className="h-3.5 w-3.5" aria-hidden />
                        {t("admin_memory.details.edit_details")}
                      </button>
                    </div>
                  </div>
                ))}

              {detailsTab === "members" && (
                <div className="flex flex-col gap-4">
                  <form onSubmit={(e) => handleAddMember(e, projectDetails.slug)} className="flex flex-col gap-2 sm:flex-row sm:items-end">
                    <label className="flex min-w-0 flex-1 flex-col gap-1.5">
                      <span className="text-sm font-medium">{t("admin_memory.members.add_member")}</span>
                      <Select
                        value={memberUserIdentifier}
                        onChange={setMemberUserIdentifier}
                        options={userOptions}
                        placeholder={
                          userOptions.length === 0
                            ? users.length === 0
                              ? t("admin_memory.members.no_users")
                              : t("admin_memory.members.all_members")
                            : t("admin_memory.members.select_user")
                        }
                        disabled={loading || userOptions.length === 0}
                      />
                    </label>
                    <div className="sm:w-40">
                      <Select value={memberRole} onChange={setMemberRole} aria-label={t("admin_memory.members.role_aria")} options={roleOptions} />
                    </div>
                    <button type="submit" disabled={loading || !memberUserIdentifier.trim()} className={cn(solidBtn, "h-[2.625rem] justify-center")}>
                      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <UserPlus className="h-3.5 w-3.5" aria-hidden />}
                      {t("admin_memory.members.add")}
                    </button>
                  </form>

                  {!projectDetails.members || projectDetails.members.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-border px-6 py-10 text-center">
                      <p className="text-sm font-medium">{t("admin_memory.members.empty_title")}</p>
                      <p className="mx-auto mt-1 max-w-[40ch] text-sm text-muted-foreground">
                        {t("admin_memory.members.empty_description")}
                      </p>
                    </div>
                  ) : (
                    <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border/70">
                      {projectDetails.members.map((member) => (
                        <li key={member.user_identifier} className="flex items-center gap-3 px-4 py-3">
                          <span
                            aria-hidden
                            style={{ "--h": hueOf(member.user_identifier) } as React.CSSProperties}
                            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[oklch(0.93_0.06_var(--h))] text-sm font-semibold uppercase text-[oklch(0.4_0.12_var(--h))] dark:bg-[oklch(0.32_0.07_var(--h))] dark:text-[oklch(0.88_0.08_var(--h))]"
                          >
                            {member.user_identifier.charAt(0)}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-sm font-medium" title={member.user_identifier}>
                              {member.user_identifier}
                            </div>
                            <div className="truncate text-xs text-muted-foreground">
                              {t("admin_memory.members.added_by", {
                                user: member.invited_by || t("admin_memory.common.system"),
                                date: formatDate(member.created_at),
                              })}
                            </div>
                          </div>
                          <span
                            className={cn(
                              "shrink-0 rounded-md px-2 py-0.5 text-xs font-medium",
                              member.role === "owner" ? "bg-foreground text-background" : "bg-secondary text-muted-foreground",
                            )}
                          >
                            {member.role === "owner" ? t("admin_memory.roles.owner") : t("admin_memory.roles.member")}
                          </span>
                          <button
                            type="button"
                            onClick={() => {
                              setMemberToDelete({ projectSlug: projectDetails.slug, userIdentifier: member.user_identifier });
                              setIsDeleteMemberOpen(true);
                            }}
                            aria-label={t("admin_memory.members.revoke_aria", { user: member.user_identifier })}
                            title={t("admin_memory.members.revoke_title")}
                            className={cn(ghostBtn, "h-8 w-8 shrink-0 justify-center px-0 hover:text-destructive")}
                          >
                            <UserMinus className="h-3.5 w-3.5" aria-hidden />
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </div>
        </Dialog>
      )}

      {/* MODAL: Create Project */}
      {isCreateOpen && (
        <Dialog
          title={t("admin_memory.create.title")}
          closeLabel={t("admin_memory.common.cancel")}
          onClose={() => setIsCreateOpen(false)}
          className="max-w-lg"
        >
          <form onSubmit={handleCreateProject} className="flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">
              {t("admin_memory.create.subtitle")}
            </p>

            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">{t("admin_memory.fields.slug")}</span>
              <input
                required
                placeholder={t("admin_memory.fields.slug_placeholder")}
                value={createSlug}
                onChange={(e) => setCreateSlug(e.target.value)}
                className={cn(inputCls, "font-mono")}
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">{t("admin_memory.fields.display_name")}</span>
              <input
                required
                placeholder={t("admin_memory.fields.display_name_placeholder")}
                value={createDisplayName}
                onChange={(e) => setCreateDisplayName(e.target.value)}
                className={inputCls}
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">
                {t("admin_memory.fields.description")}{" "}
                <span className="font-normal text-muted-foreground">{t("admin_memory.fields.optional")}</span>
              </span>
              <textarea
                placeholder={t("admin_memory.fields.description_placeholder")}
                value={createDescription}
                onChange={(e) => setCreateDescription(e.target.value)}
                rows={3}
                className={cn(inputCls, "resize-none")}
              />
            </label>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">{t("admin_memory.fields.linked_profile")}</span>
                <Select value={createProfileSlug} onChange={setCreateProfileSlug} options={profileOptions} />
              </label>

              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">{t("admin_memory.fields.scope_mode")}</span>
                <Select value={createScopeMode} onChange={setCreateScopeMode} options={scopeOptions} />
              </label>
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={() => setIsCreateOpen(false)} className={ghostBtn}>
                {t("admin_memory.common.cancel")}
              </button>
              <button type="submit" disabled={loading} className={solidBtn}>
                {loading ? t("admin_memory.create.creating") : t("admin_memory.create.submit")}
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {/* CONFIRM: Delete Project (type the name to confirm) */}
      {isDeleteProjOpen && projectToDelete && (
        <DeleteDialog
          name={projectToDelete.display_name}
          busy={loading}
          ns="admin_memory.delete"
          t={t}
          onConfirm={() => void handleDeleteProject()}
          onClose={() => {
            setIsDeleteProjOpen(false);
            setProjectToDelete(null);
          }}
        />
      )}

      {/* CONFIRM: Revoke Member Access */}
      {isDeleteMemberOpen && memberToDelete && (
        <Dialog
          title={t("admin_memory.revoke.title")}
          closeLabel={t("admin_memory.common.cancel")}
          onClose={() => {
            setIsDeleteMemberOpen(false);
            setMemberToDelete(null);
          }}
        >
          <div className="flex flex-col gap-4">
            <p className="text-sm leading-relaxed text-muted-foreground">
              {t("admin_memory.revoke.body", {
                user: "\u0000",
                project: "\u0001",
              })
                .split(/(\u0000|\u0001)/)
                .map((part, i) =>
                  part === "\u0000" ? (
                    <strong key={i} className="font-mono text-foreground">{memberToDelete.userIdentifier}</strong>
                  ) : part === "\u0001" ? (
                    <strong key={i} className="text-foreground">&quot;{memberToDelete.projectSlug}&quot;</strong>
                  ) : (
                    <span key={i}>{part}</span>
                  ),
                )}
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className={ghostBtn}
                onClick={() => {
                  setIsDeleteMemberOpen(false);
                  setMemberToDelete(null);
                }}
              >
                {t("admin_memory.common.cancel")}
              </button>
              <button
                type="button"
                onClick={() => void handleRemoveMember()}
                disabled={loading}
                className={dangerBtn}
              >
                {loading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <UserMinus className="h-3.5 w-3.5" aria-hidden />
                )}
                {loading ? t("admin_memory.revoke.revoking") : t("admin_memory.revoke.submit")}
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
