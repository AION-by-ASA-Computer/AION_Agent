"use client";

import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "@/lib/api/headers";
import { useT } from "@/lib/i18n/use-t";
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
import { DeleteDialog, nameSlot } from "@/components/ui/ConfirmDialogs";
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

const ROLE_OPTIONS = [
  { value: "member", label: "Member", description: "Can use the project's memory" },
  { value: "owner", label: "Owner", description: "Can also manage the project" },
];

const SCOPE_OPTIONS = [
  { value: "inherit", label: "Inherit", description: "Use the tenant default" },
  { value: "shared", label: "Shared", description: "Everyone shares the same results" },
  { value: "per_user", label: "Per user", description: "Results are isolated per user" },
];

const SCOPE_LABELS: Record<string, string> = Object.fromEntries(SCOPE_OPTIONS.map((o) => [o.value, o.label]));

const DELETE_TEXT: Record<string, string> = {
  "delete.title": "Delete this memory project?",
  "delete.body": `${nameSlot} will be permanently deleted, with all its members and cached queries. This cannot be undone.`,
  "delete.confirm_label": `Type ${nameSlot} to confirm`,
  "delete.cancel": "Cancel",
  "delete.confirm": "Delete",
  "delete.deleting": "Deleting…",
};

/** Page strings are plain English; adapts them to the shared dialog's translator signature. */
const deleteText = (key: string, vars?: Record<string, string | number>) =>
  (DELETE_TEXT[key] ?? key).replace(/\{\{(\w+)\}\}/g, (_, n) => String(vars?.[n] ?? ""));

function hueOf(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) % 360;
  return h;
}

interface ProfileRow {
  name: string;
  slug?: string;
}

export default function MemoryPage() {
  const t = useT();
  const [toast, setToast] = useState<ToastState>(null);
  const show = useCallback((message: string, variant: "success" | "error" = "success") => {
    setToast({ message, variant });
  }, []);

  const [projects, setProjects] = useState<Project[]>([]);
  const [profiles, setProfiles] = useState<ProfileRow[]>([]);
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

  const fetchProjects = useCallback(async (opts?: { notify?: boolean }) => {
    const notify = opts?.notify !== false;
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/query-memory/projects`);
      if (!res.ok) {
        show(`Projects: HTTP error ${res.status}`, "error");
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
      if (notify) show("Project list updated.");
    } catch (e) {
      show("Unable to load projects: " + String(e), "error");
    } finally {
      setLoading(false);
    }
  }, [show]);

  const loadAllData = useCallback(() => {
    void fetchProfiles();
    void fetchProjects({ notify: false });
  }, [fetchProfiles, fetchProjects]);

  useEffect(() => {
    loadAllData();
  }, [loadAllData]);

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createSlug.trim() || !createDisplayName.trim()) {
      show("Project slug and name are required.", "error");
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
        show(err.detail || `HTTP error ${res.status}`, "error");
      } else {
        show(`Project "${createDisplayName}" created successfully.`);
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
        show(err.detail || `HTTP error ${res.status}`, "error");
      } else {
        show(`Project "${editDisplayName}" updated successfully.`);
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
        show(`Deletion failed: HTTP error ${res.status}`, "error");
      } else {
        show(`Project "${projectToDelete.display_name}" permanently deleted.`);
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
      show("User identifier is required.", "error");
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
        show(err.detail || `HTTP error ${res.status}`, "error");
      } else {
        show(`User "${memberUserIdentifier}" added to the project.`);
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
        show(`Revocation failed: HTTP error ${res.status}`, "error");
      } else {
        show(`Access revoked for user "${userIdentifier}".`);
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
      return new Date(isoString).toLocaleDateString("en-US", {
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

  const profileOptions = [
    { value: "", label: "No profile" },
    ...profiles.map((p) => ({ value: p.slug || p.name.replace(/\s+/g, "_").toLowerCase(), label: p.name })),
  ];

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <PageToast toast={toast} onDismiss={() => setToast(null)} />

      {/* Page header */}
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">
            Memory Projects
          </h1>
          <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">
            Manage query memory contexts and control per-project member access for isolated SQL results.
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
      <section className="flex flex-col gap-4" aria-label="Active projects">
        {!loading && projects.length === 0 ? (
          <div className="flex flex-col items-center rounded-3xl border border-dashed border-border px-6 py-20 text-center">
            <Folder className="mb-4 h-8 w-8 text-muted-foreground" strokeWidth={1.5} aria-hidden />
            <h2 className="text-lg font-semibold tracking-[-0.015em]">No projects yet</h2>
            <p className="mt-1.5 max-w-[46ch] text-sm text-muted-foreground">
              Create a Memory Project to start isolating SQL query contexts per team or workflow.
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
                Loading projects…
              </div>
            ) : (
              <table className="w-full text-left" role="grid">
                <thead>
                  <tr className="border-b border-border/60 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    <th className="px-5 py-3.5" scope="col">Project</th>
                    <th className="px-5 py-3.5" scope="col">Profile</th>
                    <th className="px-5 py-3.5" scope="col">Scope</th>
                    <th className="px-5 py-3.5" scope="col">Members</th>
                    <th className="px-5 py-3.5" scope="col">Created</th>
                    <th className="px-5 py-3.5 text-right" scope="col">Actions</th>
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
                          {project.scope_mode}
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
                            title="View details & members"
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
                            title="Delete project"
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
          title={isEditingDetails ? "Edit project" : projectDetails.display_name}
          closeLabel="Close"
          onClose={closeDetails}
          className="max-w-2xl"
        >
          <div className="flex flex-col gap-5">
            <p className="-mt-1 font-mono text-xs text-muted-foreground">{projectDetails.slug}</p>

            <div role="tablist" aria-label="Project sections" className="flex gap-1 border-b border-border">
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
                    {id === "overview" ? "Overview" : "Members"}
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
                      <span className="text-sm font-medium">Display name</span>
                      <input required autoFocus value={editDisplayName} onChange={(e) => setEditDisplayName(e.target.value)} className={inputCls} />
                    </label>
                    <label className="flex flex-col gap-1.5">
                      <span className="text-sm font-medium">Description</span>
                      <textarea value={editDescription} onChange={(e) => setEditDescription(e.target.value)} rows={3} className={cn(inputCls, "resize-none")} />
                    </label>
                    <label className="flex flex-col gap-1.5">
                      <span className="text-sm font-medium">Linked profile</span>
                      <Select value={editProfileSlug} onChange={setEditProfileSlug} options={profileOptions} />
                    </label>
                    <div className="flex justify-end gap-2 pt-1">
                      <button type="button" onClick={() => setIsEditingDetails(false)} className={ghostBtn}>
                        Cancel
                      </button>
                      <button type="submit" disabled={loading} className={solidBtn}>
                        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
                        Save changes
                      </button>
                    </div>
                  </form>
                ) : (
                  <div className="flex flex-col gap-5">
                    <p className={cn("text-sm leading-relaxed", projectDetails.description ? "text-foreground" : "text-muted-foreground")}>
                      {projectDetails.description || "No description."}
                    </p>

                    <dl className="grid gap-x-6 gap-y-3 rounded-2xl border border-border/70 p-4 text-sm sm:grid-cols-2">
                      {[
                        {
                          icon: Shield,
                          label: "Source database",
                          value: projectDetails.datasource_key.startsWith("default:") ? "Not configured" : projectDetails.datasource_key,
                          mono: !projectDetails.datasource_key.startsWith("default:"),
                          hint: projectDetails.datasource_key.startsWith("default:")
                            ? "No Postgres connection was found when this project was created."
                            : "Queries learned here are kept separate from other databases.",
                        },
                        { icon: Users, label: "Scope", value: SCOPE_LABELS[projectDetails.scope_mode] ?? projectDetails.scope_mode },
                        { icon: CheckCircle, label: "Linked profile", value: projectDetails.profile_slug || "None", mono: Boolean(projectDetails.profile_slug) },
                        { icon: User, label: "Created by", value: projectDetails.created_by || "system" },
                        { icon: Calendar, label: "Created", value: formatDate(projectDetails.created_at) },
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
                        Delete project
                      </button>
                      <button type="button" onClick={() => setIsEditingDetails(true)} className={cn(outlineBtn, "ml-auto")}>
                        <Edit2 className="h-3.5 w-3.5" aria-hidden />
                        Edit details
                      </button>
                    </div>
                  </div>
                ))}

              {detailsTab === "members" && (
                <div className="flex flex-col gap-4">
                  <form onSubmit={(e) => handleAddMember(e, projectDetails.slug)} className="flex flex-col gap-2 sm:flex-row sm:items-end">
                    <label className="flex min-w-0 flex-1 flex-col gap-1.5">
                      <span className="text-sm font-medium">Add a member</span>
                      <input
                        required
                        placeholder="User ID or email"
                        value={memberUserIdentifier}
                        onChange={(e) => setMemberUserIdentifier(e.target.value)}
                        className={inputCls}
                      />
                    </label>
                    <div className="sm:w-40">
                      <Select value={memberRole} onChange={setMemberRole} aria-label="Role" options={ROLE_OPTIONS} />
                    </div>
                    <button type="submit" disabled={loading || !memberUserIdentifier.trim()} className={cn(solidBtn, "h-[2.625rem] justify-center")}>
                      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <UserPlus className="h-3.5 w-3.5" aria-hidden />}
                      Add
                    </button>
                  </form>

                  {!projectDetails.members || projectDetails.members.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-border px-6 py-10 text-center">
                      <p className="text-sm font-medium">No members yet</p>
                      <p className="mx-auto mt-1 max-w-[40ch] text-sm text-muted-foreground">
                        Only the people you add here can use this project&apos;s memory.
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
                              Added by {member.invited_by || "system"} · {formatDate(member.created_at)}
                            </div>
                          </div>
                          <span
                            className={cn(
                              "shrink-0 rounded-md px-2 py-0.5 text-xs font-medium",
                              member.role === "owner" ? "bg-foreground text-background" : "bg-secondary text-muted-foreground",
                            )}
                          >
                            {member.role === "owner" ? "Owner" : "Member"}
                          </span>
                          <button
                            type="button"
                            onClick={() => {
                              setMemberToDelete({ projectSlug: projectDetails.slug, userIdentifier: member.user_identifier });
                              setIsDeleteMemberOpen(true);
                            }}
                            aria-label={`Revoke access for ${member.user_identifier}`}
                            title="Revoke access"
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
          title="New Memory Project"
          closeLabel="Cancel"
          onClose={() => setIsCreateOpen(false)}
          className="max-w-lg"
        >
          <form onSubmit={handleCreateProject} className="flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">
              Create a project to isolate SQL query memory for a specific team or context.
            </p>

            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">Project Slug</span>
              <input
                required
                placeholder="e.g. asset_manager, internal_chatbot"
                value={createSlug}
                onChange={(e) => setCreateSlug(e.target.value)}
                className={cn(inputCls, "font-mono")}
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">Display Name</span>
              <input
                required
                placeholder="e.g. Asset Manager"
                value={createDisplayName}
                onChange={(e) => setCreateDisplayName(e.target.value)}
                className={inputCls}
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">
                Description{" "}
                <span className="font-normal text-muted-foreground">· optional</span>
              </span>
              <textarea
                placeholder="Describe this project's purpose"
                value={createDescription}
                onChange={(e) => setCreateDescription(e.target.value)}
                rows={3}
                className={cn(inputCls, "resize-none")}
              />
            </label>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">Linked Profile</span>
                <Select value={createProfileSlug} onChange={setCreateProfileSlug} options={profileOptions} />
              </label>

              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">Scope Mode</span>
                <Select value={createScopeMode} onChange={setCreateScopeMode} options={SCOPE_OPTIONS} />
              </label>
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={() => setIsCreateOpen(false)} className={ghostBtn}>
                Cancel
              </button>
              <button type="submit" disabled={loading} className={solidBtn}>
                {loading ? "Creating…" : "Create Project"}
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
          ns="delete"
          t={deleteText}
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
          title="Revoke Access"
          closeLabel="Cancel"
          onClose={() => {
            setIsDeleteMemberOpen(false);
            setMemberToDelete(null);
          }}
        >
          <div className="flex flex-col gap-4">
            <p className="text-sm leading-relaxed text-muted-foreground">
              Remove{" "}
              <strong className="font-mono text-foreground">{memberToDelete.userIdentifier}</strong>{" "}
              from project{" "}
              <strong className="text-foreground">&quot;{memberToDelete.projectSlug}&quot;</strong>.
              They will lose access to this project&apos;s SQL query memory.
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
                Cancel
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
                {loading ? "Revoking…" : "Revoke Access"}
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
