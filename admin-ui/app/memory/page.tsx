"use client";

import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "@/lib/api/headers";
import {
  Folder,
  FolderPlus,
  Users,
  UserPlus,
  UserMinus,
  Trash2,
  Edit2,
  RefreshCw,
  Loader2,
  CheckCircle,
  Shield,
  Calendar,
  User,
  Plus,
  AlertTriangle,
  Eye,
  Save,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { apiBase } from "@/lib/api";
import { PageToast, type ToastState } from "@/components/PageToast";
import { Dialog } from "@/components/profiles/Dialog";
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

interface ProfileRow {
  name: string;
  slug?: string;
}

export default function MemoryPage() {
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

  const selectCls =
    "focus-ring w-full rounded-xl border border-border bg-background px-3.5 py-2.5 text-sm transition-colors hover:border-foreground/25 focus:border-foreground/40";

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
            className={outlineBtn}
            onClick={() => void fetchProjects({ notify: true })}
            disabled={loading}
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            )}
            Refresh
          </button>
          <button
            type="button"
            className={solidBtn}
            onClick={() => setIsCreateOpen(true)}
          >
            <FolderPlus className="h-4 w-4" aria-hidden />
            New Project
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
                New Project
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

      {/* MODAL: Project Details & Members */}
      {isDetailsOpen && projectDetails && (
        <Dialog
          title={isEditingDetails ? "Edit Project" : projectDetails.display_name}
          closeLabel="Close"
          onClose={closeDetails}
          className="max-w-2xl"
        >
          <div className="flex flex-col gap-5">
            <p className="font-mono text-xs text-muted-foreground">slug: {projectDetails.slug}</p>

            {isEditingDetails ? (
              <form onSubmit={handleEditProject} className="flex flex-col gap-4">
                <label className="flex flex-col gap-1.5">
                  <span className="text-sm font-medium">Display Name</span>
                  <input
                    required
                    value={editDisplayName}
                    onChange={(e) => setEditDisplayName(e.target.value)}
                    className={inputCls}
                  />
                </label>

                <label className="flex flex-col gap-1.5">
                  <span className="text-sm font-medium">Description</span>
                  <textarea
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    rows={3}
                    className={cn(inputCls, "resize-none")}
                  />
                </label>

                <label className="flex flex-col gap-1.5">
                  <span className="text-sm font-medium">Linked Profile</span>
                  <select
                    value={editProfileSlug}
                    onChange={(e) => setEditProfileSlug(e.target.value)}
                    className={selectCls}
                  >
                    <option value="">— No Profile —</option>
                    {profiles.map((p) => {
                      const s = p.slug || p.name.replace(/\s+/g, "_").toLowerCase();
                      return (
                        <option key={p.name} value={s}>
                          {p.name}
                        </option>
                      );
                    })}
                  </select>
                </label>

                <div className="flex justify-end gap-2 pt-1">
                  <button type="button" onClick={() => setIsEditingDetails(false)} className={ghostBtn}>
                    Cancel
                  </button>
                  <button type="submit" disabled={loading} className={solidBtn}>
                    {loading ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    ) : (
                      <Save className="h-3.5 w-3.5" aria-hidden />
                    )}
                    Save Details
                  </button>
                </div>
              </form>
            ) : (
              <>
                {projectDetails.description && (
                  <p className="text-sm leading-relaxed text-muted-foreground">{projectDetails.description}</p>
                )}

                <div className="rounded-2xl border border-border/60 bg-secondary/30 px-4 py-3">
                  <dl className="grid gap-2 text-sm sm:grid-cols-2">
                    <div className="flex items-center gap-2">
                      <Shield className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      <dt className="text-muted-foreground">Datasource</dt>
                      <dd className="ml-auto font-mono text-xs font-medium">{projectDetails.datasource_key}</dd>
                    </div>
                    <div className="flex items-center gap-2">
                      <User className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      <dt className="text-muted-foreground">Creator</dt>
                      <dd className="ml-auto text-xs font-medium">{projectDetails.created_by || "system"}</dd>
                    </div>
                    <div className="flex items-center gap-2">
                      <Shield className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      <dt className="text-muted-foreground">Scope</dt>
                      <dd className="ml-auto font-mono text-xs font-medium uppercase">{projectDetails.scope_mode}</dd>
                    </div>
                    <div className="flex items-center gap-2">
                      <Calendar className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      <dt className="text-muted-foreground">Created</dt>
                      <dd className="ml-auto text-xs tabular-nums">{formatDate(projectDetails.created_at)}</dd>
                    </div>
                    {projectDetails.profile_slug && (
                      <div className="flex items-center gap-2 sm:col-span-2">
                        <CheckCircle className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                        <dt className="text-muted-foreground">Profile</dt>
                        <dd className="ml-auto font-mono text-xs font-medium">{projectDetails.profile_slug}</dd>
                      </div>
                    )}
                  </dl>
                </div>

                <div className="flex justify-end">
                  <button type="button" onClick={() => setIsEditingDetails(true)} className={ghostBtn}>
                    <Edit2 className="h-3.5 w-3.5" aria-hidden />
                    Edit Details
                  </button>
                </div>
              </>
            )}

            {/* Members section */}
            <div className="flex flex-col gap-3 border-t border-border/60 pt-4">
              <h3 className="text-sm font-semibold">
                Members
                <span className="ml-1.5 rounded-full bg-secondary px-1.5 py-px text-xs tabular-nums text-muted-foreground">
                  {projectDetails.members?.length || 0}
                </span>
              </h3>

              <form
                onSubmit={(e) => handleAddMember(e, projectDetails.slug)}
                className="flex flex-col gap-2 sm:flex-row sm:items-end"
              >
                <label className="flex flex-1 flex-col gap-1.5">
                  <span className="text-xs font-medium text-muted-foreground">User ID or email</span>
                  <input
                    required
                    placeholder="e.g. mario.rossi, user@example.com"
                    value={memberUserIdentifier}
                    onChange={(e) => setMemberUserIdentifier(e.target.value)}
                    className={inputCls}
                  />
                </label>
                <label className="flex w-full flex-col gap-1.5 sm:w-36">
                  <span className="text-xs font-medium text-muted-foreground">Role</span>
                  <select
                    value={memberRole}
                    onChange={(e) => setMemberRole(e.target.value)}
                    className={selectCls}
                  >
                    <option value="member">Member</option>
                    <option value="owner">Owner</option>
                  </select>
                </label>
                <button type="submit" disabled={loading} className={solidBtn}>
                  {loading ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  ) : (
                    <UserPlus className="h-3.5 w-3.5" aria-hidden />
                  )}
                  Add
                </button>
              </form>

              {!projectDetails.members || projectDetails.members.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">No members enrolled.</p>
              ) : (
                <div className="overflow-hidden rounded-2xl border border-border/60">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-border/40 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                        <th className="px-4 py-3" scope="col">User</th>
                        <th className="px-4 py-3" scope="col">Role</th>
                        <th className="px-4 py-3" scope="col">Added By</th>
                        <th className="px-4 py-3 text-right" scope="col">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/40">
                      {projectDetails.members.map((member) => (
                        <tr key={member.user_identifier} className="transition-colors hover:bg-secondary/30">
                          <td
                            className="max-w-[180px] truncate px-4 py-3 font-mono text-xs font-medium"
                            title={member.user_identifier}
                          >
                            {member.user_identifier}
                          </td>
                          <td className="px-4 py-3">
                            <span className="rounded-lg border border-border bg-secondary px-2 py-0.5 text-xs font-medium uppercase tracking-wide">
                              {member.role}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-xs text-muted-foreground">
                            {member.invited_by || "system"}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <button
                              type="button"
                              onClick={() => {
                                setMemberToDelete({
                                  projectSlug: projectDetails.slug,
                                  userIdentifier: member.user_identifier,
                                });
                                setIsDeleteMemberOpen(true);
                              }}
                              title="Revoke access"
                              className={cn(ghostBtn, "hover:text-destructive")}
                            >
                              <UserMinus className="h-3.5 w-3.5" aria-hidden />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Footer actions */}
            <div className="flex items-center gap-2 border-t border-border/60 pt-4">
              <button
                type="button"
                onClick={() => {
                  setProjectToDelete(projectDetails);
                  setIsDeleteProjOpen(true);
                }}
                className={cn(ghostBtn, "mr-auto hover:text-destructive")}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
                Delete Project
              </button>
              <button type="button" onClick={closeDetails} className={ghostBtn}>
                Close
              </button>
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
                <select
                  value={createProfileSlug}
                  onChange={(e) => setCreateProfileSlug(e.target.value)}
                  className={selectCls}
                >
                  <option value="">— No Profile —</option>
                  {profiles.map((p) => {
                    const s = p.slug || p.name.replace(/\s+/g, "_").toLowerCase();
                    return (
                      <option key={p.name} value={s}>
                        {p.name}
                      </option>
                    );
                  })}
                </select>
              </label>

              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">Scope Mode</span>
                <select
                  value={createScopeMode}
                  onChange={(e) => setCreateScopeMode(e.target.value)}
                  className={selectCls}
                >
                  <option value="inherit">Inherit (tenant default)</option>
                  <option value="shared">Shared (everyone shares)</option>
                  <option value="per_user">Per User (isolated)</option>
                </select>
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

      {/* CONFIRM: Delete Project */}
      {isDeleteProjOpen && projectToDelete && (
        <Dialog
          title="Delete Project"
          closeLabel="Cancel"
          onClose={() => {
            setIsDeleteProjOpen(false);
            setProjectToDelete(null);
          }}
        >
          <div className="flex flex-col gap-4">
            <div
              className="flex items-start gap-3 rounded-2xl bg-destructive/10 px-4 py-3 text-sm"
              role="alert"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
              <p>
                You are about to permanently delete{" "}
                <strong className="font-semibold">&quot;{projectToDelete.display_name}&quot;</strong>{" "}
                ({projectToDelete.slug}). All associated members and cached queries will be removed.
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className={ghostBtn}
                onClick={() => {
                  setIsDeleteProjOpen(false);
                  setProjectToDelete(null);
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleDeleteProject()}
                disabled={loading}
                className={dangerBtn}
              >
                {loading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                )}
                {loading ? "Deleting…" : "Delete Project"}
              </button>
            </div>
          </div>
        </Dialog>
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
