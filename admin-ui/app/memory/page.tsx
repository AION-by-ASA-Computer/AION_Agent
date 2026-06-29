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
  Info,
  CheckCircle,
  Shield,
  Calendar,
  User,
  X,
  Plus,
  AlertTriangle,
  Eye,
  Save,
} from "lucide-react";
import { apiBase } from "@/lib/api";
import { PageToast, type ToastState } from "@/components/PageToast";

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

  // Modals state
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const [projectDetails, setProjectDetails] = useState<Project | null>(null);
  const [isEditingDetails, setIsEditingDetails] = useState(false);

  // Delete confirmations
  const [isDeleteProjOpen, setIsDeleteProjOpen] = useState(false);
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null);
  const [isDeleteMemberOpen, setIsDeleteMemberOpen] = useState(false);
  const [memberToDelete, setMemberToDelete] = useState<{ projectSlug: string; userIdentifier: string } | null>(null);

  // Form inputs state
  const [createSlug, setCreateSlug] = useState("");
  const [createDisplayName, setCreateDisplayName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [createProfileSlug, setCreateProfileSlug] = useState("");
  const [createScopeMode, setCreateScopeMode] = useState("inherit");

  const [editDisplayName, setEditDisplayName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editProfileSlug, setEditProfileSlug] = useState("");
  const [editScopeMode, setEditScopeMode] = useState("inherit");

  const [memberUserIdentifier, setMemberUserIdentifier] = useState("");
  const [memberRole, setMemberRole] = useState("member");

  // Fetch functions
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

      // Keep detail modal updated if open
      setProjectDetails((prevDetails) => {
        if (!prevDetails) return null;
        const updated = projectList.find((p) => p.slug === prevDetails.slug);
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

  // Operations
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
          scope_mode: editScopeMode,
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
        show(` deletion failed: HTTP error ${res.status}`, "error");
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
    setEditScopeMode(p.scope_mode);
    setIsEditingDetails(false);
    setIsDetailsOpen(true);
  };

  // Formatter utilities
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

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-8 pb-12">
      <PageToast toast={toast} onDismiss={() => setToast(null)} />

      {/* Header section with Stats */}
      <header className="relative overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-br from-violet-950/20 via-[#0d0d0d] to-[#0a0a0a] p-6 sm:p-8">
        <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-violet-600/10 blur-3xl" />
        <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between relative">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-violet-500/30 bg-violet-500/10 px-3 py-1 text-xs font-bold uppercase tracking-wider text-violet-300">
              <Shield className="h-3.5 w-3.5" /> Security Administration
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight text-white md:text-4xl">
              SQL Projects & Members
            </h1>
            <p className="max-w-2xl text-sm leading-relaxed text-gray-400">
              Manage the isolation of SQL query contexts (projects) and define the users authorized to access and manage each SQL query memory scope.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => void fetchProjects({ notify: true })}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-[#161616] px-4 py-3 text-sm font-bold text-gray-300 hover:bg-[#202020] hover:text-white transition cursor-pointer disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Refresh
            </button>
            <button
              onClick={() => setIsCreateOpen(true)}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 px-5 py-3 text-sm font-bold text-white shadow-lg shadow-violet-500/25 transition transform active:scale-95 cursor-pointer"
            >
              <FolderPlus className="h-4 w-4" /> New Project
            </button>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="mt-8 grid gap-4 grid-cols-2 border-t border-white/5 pt-6">
          <div className="space-y-1">
            <span className="text-xs text-gray-500 font-bold uppercase tracking-wider">Projects Created</span>
            <div className="text-2xl font-black text-white">{projects.length}</div>
          </div>
          <div className="space-y-1">
            <span className="text-xs text-gray-500 font-bold uppercase tracking-wider">Total Members</span>
            <div className="text-2xl font-black text-violet-400">
              {projects.reduce((acc, p) => acc + (p.members?.length || 0), 0)}
            </div>
          </div>
        </div>
      </header>

      {/* Projects Table List */}
      <section className="space-y-6">
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <Folder className="h-5 w-5 text-violet-400" /> Active Projects
        </h2>

        {projects.length === 0 && !loading ? (
          <div className="rounded-2xl border border-dashed border-white/10 p-12 text-center flex flex-col items-center justify-center space-y-4">
            <Folder className="h-12 w-12 text-gray-600" />
            <div>
              <p className="text-base font-semibold text-gray-300">No projects found</p>
              <p className="text-xs text-gray-500 mt-1">Create a new SQL Query project to get started.</p>
            </div>
            <button
              onClick={() => setIsCreateOpen(true)}
              className="inline-flex items-center gap-2 rounded-xl bg-violet-600/20 border border-violet-500/30 px-4 py-2 text-xs font-bold text-violet-300 hover:bg-violet-600/30 transition cursor-pointer"
            >
              <Plus className="h-3.5 w-3.5" /> New Project
            </button>
          </div>
        ) : (
          <div className="glass-card overflow-hidden border border-white/10 rounded-3xl bg-gradient-to-b from-[#181818]/90 to-[#121212]/90 shadow-2xl relative">
            <table className="w-full text-left">
              <thead>
                <tr className="bg-black/40 border-b border-white/10 text-xs font-bold uppercase text-gray-400 tracking-wider">
                  <th className="px-6 py-4">Project</th>
                  <th className="px-6 py-4">Profile</th>
                  <th className="px-6 py-4">Scope Mode</th>
                  <th className="px-6 py-4">Members</th>
                  <th className="px-6 py-4">Created On</th>
                  <th className="px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5 text-sm text-gray-300">
                {projects.map((project) => (
                  <tr
                    key={project.id}
                    className="hover:bg-white/[0.02] transition-colors group cursor-pointer"
                    onClick={() => openDetailsModal(project)}
                  >
                    <td className="px-6 py-4">
                      <div className="font-bold text-white">{project.display_name}</div>
                      <div className="text-xs text-gray-500 font-mono mt-0.5">{project.slug}</div>
                    </td>
                    <td className="px-6 py-4">
                      {project.profile_slug ? (
                        <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                          {project.profile_slug}
                        </span>
                      ) : (
                        <span className="text-gray-600 italic font-mono">-</span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-violet-500/10 border border-violet-500/20 text-violet-300 uppercase tracking-wide">
                        {project.scope_mode}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-[#1b1b1b] border border-white/10 px-2.5 py-1 text-xs font-bold text-white shadow-inner">
                        <Users className="h-3.5 w-3.5 text-violet-400" />
                        {project.members?.length || 0}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-xs text-gray-400">
                      {formatDate(project.created_at)}
                    </td>
                    <td className="px-6 py-4 text-right space-x-2" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => openDetailsModal(project)}
                        title="Details & Members"
                        className="p-2.5 bg-violet-500/10 hover:bg-violet-500/20 text-violet-400 border border-violet-500/20 rounded-xl transition cursor-pointer inline-flex items-center justify-center mr-1"
                      >
                        <Eye className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => {
                          setProjectToDelete(project);
                          setIsDeleteProjOpen(true);
                        }}
                        title="Delete project"
                        className="p-2.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 rounded-xl transition cursor-pointer inline-flex items-center justify-center"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* MODAL: Project Details & Members */}
      {isDetailsOpen && projectDetails && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#181818] border border-white/10 rounded-3xl w-full max-w-2xl overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
            {/* Modal Header */}
            <div className="p-6 border-b border-white/5 flex justify-between items-center bg-white/5 shrink-0">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-violet-600/10 border border-violet-500/20 rounded-xl text-violet-400">
                  <Folder className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white">
                    {isEditingDetails ? "Edit Configuration" : projectDetails.display_name}
                  </h3>
                  <p className="text-xs text-gray-400 font-mono">slug: {projectDetails.slug}</p>
                </div>
              </div>
              <button
                onClick={() => {
                  setIsDetailsOpen(false);
                  setProjectDetails(null);
                  setIsEditingDetails(false);
                }}
                className="p-1.5 text-gray-500 hover:text-white hover:bg-white/5 rounded-lg transition cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Scrollable Content */}
            <div className="p-6 space-y-6 overflow-y-auto flex-1 custom-scrollbar">
              {isEditingDetails ? (
                /* EDIT DETAILS FORM */
                <form onSubmit={handleEditProject} className="space-y-4">
                  <div className="space-y-1">
                    <label className="text-xs font-bold uppercase tracking-wider text-gray-400">Display Name</label>
                    <input
                      required
                      value={editDisplayName}
                      onChange={(e) => setEditDisplayName(e.target.value)}
                      className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:border-violet-500 focus:ring-1 focus:ring-violet-500 outline-none transition font-semibold"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="text-xs font-bold uppercase tracking-wider text-gray-400">Description</label>
                    <textarea
                      value={editDescription}
                      onChange={(e) => setEditDescription(e.target.value)}
                      className="w-full min-h-[80px] bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:border-violet-500 focus:ring-1 focus:ring-violet-500 outline-none transition"
                    />
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-1">
                      <label className="text-xs font-bold uppercase tracking-wider text-gray-400">Linked Profile</label>
                      <select
                        value={editProfileSlug}
                        onChange={(e) => setEditProfileSlug(e.target.value)}
                        className="w-full bg-black border border-white/10 rounded-xl p-3 text-sm text-white focus:border-violet-500 outline-none transition"
                      >
                        <option value="">— — No Profile — —</option>
                        {profiles.map((p) => {
                          const s = p.slug || p.name.replace(/\s+/g, "_").toLowerCase();
                          return (
                            <option key={p.name} value={s}>
                              {p.name}
                            </option>
                          );
                        })}
                      </select>
                    </div>

                  </div>

                  <div className="flex justify-end gap-2 pt-2">
                    <button
                      type="button"
                      onClick={() => setIsEditingDetails(false)}
                      className="px-4 py-2 bg-white/5 hover:bg-white/10 text-gray-300 border border-white/10 rounded-xl text-xs font-semibold transition cursor-pointer"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={loading}
                      className="px-5 py-2 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl font-bold text-xs transition flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                    >
                      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                      Save Details
                    </button>
                  </div>
                </form>
              ) : (
                /* VIEW DETAILS METADATA */
                <>
                  {/* Description */}
                  {projectDetails.description && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold uppercase tracking-wider text-gray-500">Description</span>
                        <button
                          onClick={() => setIsEditingDetails(true)}
                          className="text-xs font-bold text-violet-400 hover:text-violet-300 transition flex items-center gap-1 cursor-pointer"
                        >
                          <Edit2 className="h-3 w-3" /> Edit Details
                        </button>
                      </div>
                      <p className="text-xs text-gray-400 leading-relaxed bg-black/25 rounded-2xl p-4 border border-white/5">
                        {projectDetails.description}
                      </p>
                    </div>
                  )}

                  {/* Specs Info Grid */}
                  <div className="space-y-2">
                    {!projectDetails.description && (
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold uppercase tracking-wider text-gray-500">Project Metadata</span>
                        <button
                          onClick={() => setIsEditingDetails(true)}
                          className="text-xs font-bold text-violet-400 hover:text-violet-300 transition flex items-center gap-1 cursor-pointer"
                        >
                          <Edit2 className="h-3 w-3" /> Edit Details
                        </button>
                      </div>
                    )}
                    {projectDetails.description && (
                      <span className="text-xs font-bold uppercase tracking-wider text-gray-500">Project Metadata</span>
                    )}
                    <div className="grid gap-3 sm:grid-cols-2 text-xs text-gray-400 bg-white/[0.01] rounded-2xl p-4 border border-white/5">
                      <div className="flex items-center gap-2">
                        <Shield className="h-4 w-4 text-gray-600 shrink-0" />
                        <span>Datasource: <strong className="text-white font-mono">{projectDetails.datasource_key}</strong></span>
                      </div>
                      <div className="flex items-center gap-2">
                        <User className="h-4 w-4 text-gray-600 shrink-0" />
                        <span>Creator: <strong className="text-white">{projectDetails.created_by || "system"}</strong></span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Shield className="h-4 w-4 text-gray-600 shrink-0" />
                        <span>Scope Mode: <strong className="text-white uppercase font-mono">{projectDetails.scope_mode}</strong></span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Calendar className="h-4 w-4 text-gray-600 shrink-0" />
                        <span>Created: <strong className="text-white">{formatDate(projectDetails.created_at)}</strong></span>
                      </div>
                      {projectDetails.profile_slug && (
                        <div className="flex items-center gap-2 sm:col-span-2">
                          <CheckCircle className="h-4 w-4 text-emerald-600 shrink-0" />
                          <span>Linked Profile: <strong className="text-emerald-400 font-mono">{projectDetails.profile_slug}</strong></span>
                        </div>
                      )}
                    </div>
                  </div>
                </>
              )}

              {/* Members Section (always visible in view mode, optional/visible during edit as well, let's keep it visible) */}
              <div className="space-y-4 pt-4 border-t border-white/5">
                <div className="flex items-center justify-between border-b border-white/5 pb-2">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-gray-400 flex items-center gap-1.5">
                    <Users className="h-3.5 w-3.5 text-violet-400" /> Authorized Members ({projectDetails.members?.length || 0})
                  </h4>
                </div>

                {/* Add member form inline */}
                <form
                  onSubmit={(e) => handleAddMember(e, projectDetails.slug)}
                  className="flex flex-col sm:flex-row items-end gap-3 bg-white/[0.01] rounded-2xl p-4 border border-white/5"
                >
                  <div className="w-full sm:flex-1 space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500">ID User (Username / E-mail)</label>
                    <input
                      required
                      placeholder="e.g. mario.rossi, user@example.com"
                      value={memberUserIdentifier}
                      onChange={(e) => setMemberUserIdentifier(e.target.value)}
                      className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-xs text-white focus:border-violet-500 outline-none transition font-semibold"
                    />
                  </div>
                  <div className="w-full sm:w-36 space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Role</label>
                    <select
                      value={memberRole}
                      onChange={(e) => setMemberRole(e.target.value)}
                      className="w-full bg-black border border-white/10 rounded-xl px-3 py-2.5 text-xs text-white focus:border-violet-500 outline-none transition"
                    >
                      <option value="member">Member</option>
                      <option value="owner">Owner</option>
                    </select>
                  </div>
                  <button
                    type="submit"
                    disabled={loading}
                    className="w-full sm:w-auto px-5 py-2.5 bg-violet-600 hover:bg-violet-500 text-white rounded-xl text-xs font-bold transition flex items-center justify-center gap-1.5 h-10 shrink-0 cursor-pointer shadow-lg shadow-violet-600/20"
                  >
                    {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}
                    Add
                  </button>
                </form>

                {/* Members list */}
                {(!projectDetails.members || projectDetails.members.length === 0) ? (
                  <div className="text-center py-6 text-xs text-gray-600 italic">No users enrolled.</div>
                ) : (
                  <div className="overflow-hidden rounded-2xl border border-white/5 bg-black/25">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="bg-white/5 border-b border-white/5 text-gray-500 font-bold uppercase tracking-wider text-[10px]">
                          <th className="px-4 py-3">User</th>
                          <th className="px-4 py-3">Role</th>
                          <th className="px-4 py-3">Added By</th>
                          <th className="px-4 py-3 text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5 font-medium text-gray-300">
                        {projectDetails.members.map((member) => (
                          <tr key={member.user_identifier} className="hover:bg-white/[0.01] transition-colors">
                            <td className="px-4 py-3 font-mono text-[11px] max-w-[200px] truncate" title={member.user_identifier}>
                              {member.user_identifier}
                            </td>
                            <td className="px-4 py-3">
                              <span
                                className={`text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${member.role === "owner"
                                  ? "bg-amber-500/10 border border-amber-500/20 text-amber-400"
                                  : "bg-blue-500/10 border border-blue-500/20 text-blue-400"
                                  }`}
                              >
                                {member.role}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-gray-500">{member.invited_by || "system"}</td>
                            <td className="px-4 py-3 text-right">
                              <button
                                onClick={() => {
                                  setMemberToDelete({ projectSlug: projectDetails.slug, userIdentifier: member.user_identifier });
                                  setIsDeleteMemberOpen(true);
                                }}
                                title="Revoke access"
                                className="p-2 rounded-lg bg-red-500/10 border border-red-500/10 text-red-400 hover:text-white hover:bg-red-600 hover:border-red-600 transition cursor-pointer"
                              >
                                <UserMinus className="h-3.5 w-3.5" />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>

            {/* Modal Footer */}
            <div className="p-6 border-t border-white/5 flex justify-end gap-3 bg-black/20 shrink-0">
              <button
                type="button"
                onClick={() => {
                  setProjectToDelete(projectDetails);
                  setIsDeleteProjOpen(true);
                }}
                className="px-5 py-2.5 bg-red-600/10 hover:bg-red-600 text-red-400 hover:text-white border border-red-500/20 rounded-xl text-sm font-semibold transition cursor-pointer mr-auto"
              >
                Delete Project
              </button>
              <button
                type="button"
                onClick={() => {
                  setIsDetailsOpen(false);
                  setProjectDetails(null);
                  setIsEditingDetails(false);
                }}
                className="px-6 py-2.5 bg-white/5 hover:bg-white/10 text-gray-300 border border-white/10 rounded-xl text-sm font-semibold transition cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: Create Project */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#181818] border border-white/10 rounded-3xl w-full max-w-lg overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
            <div className="p-6 border-b border-white/5 flex justify-between items-center bg-white/5 bg-gradient-to-r from-white/[0.01] to-white/[0.03] shrink-0">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-violet-600/10 border border-violet-500/20 rounded-xl text-violet-400">
                  <FolderPlus className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-white">New Project SQL Query</h3>
                  <p className="text-xs text-gray-400">Create a new query caching isolation</p>
                </div>
              </div>
              <button
                onClick={() => setIsCreateOpen(false)}
                className="p-1.5 text-gray-500 hover:text-white hover:bg-white/5 rounded-lg transition cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateProject} className="flex flex-col flex-1 overflow-hidden">
              <div className="p-6 space-y-4 overflow-y-auto flex-1 custom-scrollbar">
                <div className="space-y-1">
                  <label className="text-xs font-bold uppercase tracking-wider text-gray-400">Project Slug</label>
                  <input
                    required
                    placeholder="e.g. asset_manager, internal_chatbot"
                    value={createSlug}
                    onChange={(e) => setCreateSlug(e.target.value)}
                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:border-violet-500 focus:ring-1 focus:ring-violet-500 outline-none transition font-semibold"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-bold uppercase tracking-wider text-gray-400">Display Name</label>
                  <input
                    required
                    placeholder="e.g. Asset Manager"
                    value={createDisplayName}
                    onChange={(e) => setCreateDisplayName(e.target.value)}
                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:border-violet-500 focus:ring-1 focus:ring-violet-500 outline-none transition font-semibold"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-bold uppercase tracking-wider text-gray-400">Description</label>
                  <textarea
                    placeholder="Optional description of this project's purpose"
                    value={createDescription}
                    onChange={(e) => setCreateDescription(e.target.value)}
                    className="w-full min-h-[80px] bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:border-violet-500 focus:ring-1 focus:ring-violet-500 outline-none transition"
                  />
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1">
                    <label className="text-xs font-bold uppercase tracking-wider text-gray-400">Linked Profile</label>
                    <select
                      value={createProfileSlug}
                      onChange={(e) => setCreateProfileSlug(e.target.value)}
                      className="w-full bg-black border border-white/10 rounded-xl p-3 text-sm text-white focus:border-violet-500 outline-none transition"
                    >
                      <option value="">— — No Profile — —</option>
                      {profiles.map((p) => {
                        const s = p.slug || p.name.replace(/\s+/g, "_").toLowerCase();
                        return (
                          <option key={p.name} value={s}>
                            {p.name}
                          </option>
                        );
                      })}
                    </select>
                  </div>

                  <div className="space-y-1">
                    <label className="text-xs font-bold uppercase tracking-wider text-gray-400">Scope Mode</label>
                    <select
                      value={createScopeMode}
                      onChange={(e) => setCreateScopeMode(e.target.value)}
                      className="w-full bg-black border border-white/10 rounded-xl p-3 text-sm text-white focus:border-violet-500 outline-none transition"
                    >
                      <option value="inherit">Inherit (Use tenant default)</option>
                      <option value="shared">Shared (Everyone shares)</option>
                      <option value="per_user">Per User (Isolated queries)</option>
                    </select>
                  </div>
                </div>
              </div>

              <div className="p-6 border-t border-white/5 flex justify-end gap-3 bg-black/20 shrink-0">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="px-5 py-2.5 bg-white/5 hover:bg-white/10 text-gray-300 border border-white/10 rounded-xl text-sm font-semibold transition cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="px-6 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl font-bold text-sm transition shadow-lg shadow-violet-500/20 cursor-pointer disabled:opacity-50"
                >
                  {loading ? "Creating..." : "Create Project"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* CONFIRMATION: Delete Project */}
      {isDeleteProjOpen && projectToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/90 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl w-full max-w-md overflow-hidden shadow-2xl">
            <div className="p-6 border-b border-white/5 bg-white/5 flex items-center gap-3">
              <div className="p-2 bg-red-600/10 border border-red-500/20 rounded-xl text-red-400">
                <Trash2 className="w-5 h-5" />
              </div>
              <h3 className="text-lg font-bold text-white">Delete Project</h3>
            </div>
            <div className="p-6 space-y-4">
              <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-200 text-xs leading-relaxed flex gap-2">
                <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
                <div>
                  <strong className="text-white">WARNING: Irreversible Operation</strong>
                  <p className="mt-1">
                    You are about to permanently delete the project{" "}
                    <b className="text-white font-bold">"{projectToDelete.display_name}"</b> ({projectToDelete.slug}).
                  </p>
                  <p className="mt-2 text-red-300">
                    All associated members and cached SQL queries in this project will be permanently deleted
                    from the database.
                  </p>
                </div>
              </div>
              <p className="text-xs text-gray-400">Confirm deletion?</p>
            </div>
            <div className="p-6 border-t border-white/5 flex justify-end gap-3 bg-black/20">
              <button
                onClick={() => {
                  setIsDeleteProjOpen(false);
                  setProjectToDelete(null);
                }}
                className="px-5 py-2.5 text-sm font-semibold text-gray-400 hover:text-white transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={() => void handleDeleteProject()}
                disabled={loading}
                className="bg-red-600 hover:bg-red-500 text-white px-6 py-2.5 rounded-xl text-sm font-bold transition shadow-lg shadow-red-600/20 cursor-pointer disabled:opacity-50"
              >
                {loading ? "Deleting..." : "Delete Project"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* CONFIRMATION: Revoke Access (Delete Member) */}
      {isDeleteMemberOpen && memberToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/90 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl w-full max-w-md overflow-hidden shadow-2xl">
            <div className="p-6 border-b border-white/5 bg-white/5 flex items-center gap-3">
              <div className="p-2 bg-red-600/10 border border-red-500/20 rounded-xl text-red-400">
                <UserMinus className="w-5 h-5" />
              </div>
              <h3 className="text-lg font-bold text-white">Revoke Access User</h3>
            </div>
            <div className="p-6 space-y-3">
              <p className="text-sm text-gray-300 leading-relaxed">
                You are about to remove user <strong className="text-white font-mono">{memberToDelete.userIdentifier}</strong> from the project <strong className="text-white">"{memberToDelete.projectSlug}"</strong>.
              </p>
              <p className="text-xs text-gray-500">The user will lose access to this SQL query memory isolation.</p>
            </div>
            <div className="p-6 border-t border-white/5 flex justify-end gap-3 bg-black/20">
              <button
                onClick={() => {
                  setIsDeleteMemberOpen(false);
                  setMemberToDelete(null);
                }}
                className="px-5 py-2.5 text-sm font-semibold text-gray-400 hover:text-white transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={() => void handleRemoveMember()}
                disabled={loading}
                className="bg-red-600 hover:bg-red-500 text-white px-6 py-2.5 rounded-xl text-sm font-bold transition shadow-lg shadow-red-600/20 cursor-pointer disabled:opacity-50"
              >
                {loading ? "Revoking..." : "Revoke Access"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
