"use client";

import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api/headers"
import { UserPlus, Settings2, Trash2, Save, X, Cpu, Search, Check, Plus, Layers, ShieldCheck, Sparkles, Star, ChevronRight, ChevronDown, ChevronUp, AlertTriangle, Download, Upload, Terminal, FileText, Code2 } from "lucide-react";
import { apiBase } from "@/lib/api";
import { PageToast, ToastState } from "@/components/PageToast";
import { BlockMarkdownEditor } from "@/components/BlockMarkdownEditor";
import { HeaderDropdown } from "@/components/HeaderDropdown";

/** Canonical profile key for API paths (backend resolves slug only). */
function profileSlug(p: { slug?: string; name?: string }): string {
  if (p.slug) return p.slug;
  return (p.name || "").trim().toLowerCase().replace(/\s+/g, "_");
}

export default function Profiles() {
  const [profiles, setProfiles] = useState<any[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [toast, setToast] = useState<ToastState>(null);

  const [availableSkills, setAvailableSkills] = useState<Record<string, { description: string; tags: string[] }>>({});
  const [availableMCPs, setAvailableMCPs] = useState<Record<string, string>>({});
  const [skillTooltip, setSkillTooltip] = useState<{ name: string; x: number; y: number; height?: number } | null>(null);
  const [mcpTooltip, setMcpTooltip] = useState<{ name: string; x: number; y: number; height?: number } | null>(null);

  const [skillSearch, setSkillSearch] = useState("");
  const [skillDropdownOpen, setSkillDropdownOpen] = useState(false);
  const [mcpSearch, setMcpSearch] = useState("");
  const [mcpDropdownOpen, setMcpDropdownOpen] = useState(false);
  const [showSelectedSkillsOnly, setShowSelectedSkillsOnly] = useState(false);
  const [showSelectedMCPsOnly, setShowSelectedMCPsOnly] = useState(false);

  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [deleteConfirmInput, setDeleteConfirmInput] = useState("");
  const NATIVE_TOOL_BUNDLES = ["web_research"];

  useEffect(() => {
    fetchProfiles();
    fetchMetadata();
  }, []);

  const fetchMetadata = async () => {
    try {
      const [skillsRes, mcpRes, nativeToolsRes] = await Promise.all([
        apiFetch(`${apiBase()}/admin/skills`),
        apiFetch(`${apiBase()}/admin/registry`),
        apiFetch(`${apiBase()}/admin/native-tools`)
      ]);
      const skillsMap: Record<string, { description: string; tags: string[] }> = await skillsRes.json();
      const mcp: Record<string, any> = await mcpRes.json();
      const nativeTools = await nativeToolsRes.json();
      const mcpMap: Record<string, string> = {};
      for (const [key, cfg] of Object.entries(mcp)) {
        mcpMap[key] = (cfg as any)?.description || "";
      }
      if (nativeTools && nativeTools.bundles) {
        for (const [key, bundle] of Object.entries(nativeTools.bundles)) {
          mcpMap[key] = (bundle as any)?.description || "";
        }
      }
      setAvailableSkills(skillsMap);
      setAvailableMCPs(mcpMap);
    } catch (e) {
      console.error("Failed to fetch available metadata", e);
    }
  };

  const fetchProfiles = async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles`);
      if (!res.ok) throw new Error("Error loading profiles");
      const data = await res.json();
      setProfiles(data);
      if (data.length > 0 && !selectedProfile) {
        // Automatically fetch details for the first profile in the list
        const detailRes = await apiFetch(
          `${apiBase()}/admin/profiles/${encodeURIComponent(profileSlug(data[0]))}`
        );
        if (detailRes.ok) {
          const detailData = await detailRes.json();
          setSelectedProfile({
            ...detailData,
            native_tool_groups: Array.isArray(detailData.native_tool_groups) ? detailData.native_tool_groups : [],
          });
        }
      }
    } catch (e: any) {
      console.error(e);
      setToast({ message: "Could not connect to backend: " + e.message, variant: "error" });
    }
  };

  const handleEdit = async (slug: string) => {
    setLoadingProfile(true);
    try {
      const res = await apiFetch(
        `${apiBase()}/admin/profiles/${encodeURIComponent(slug)}`
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const detail =
          typeof err?.detail === "string"
            ? err.detail
            : `HTTP ${res.status}`;
        throw new Error(detail);
      }
      const data = await res.json();
      setSelectedProfile({
        ...data,
        native_tool_groups: Array.isArray(data.native_tool_groups) ? data.native_tool_groups : [],
      });
    } catch (e: any) {
      setToast({
        message: `Error loading profile: ${e?.message || "unknown error"}`,
        variant: "error",
      });
    } finally {
      setLoadingProfile(false);
    }
  };

  const handleNewProfile = () => {
    setSelectedProfile({
      name: "",
      description: "Custom specialized AI agent",
      instructions: "You are an expert AI assistant dedicated to assisting the user with specialized tasks.",
      skills: [],
      critical_skills: [],
      mcp_servers: []
    });
  };

  const handleDelete = (name: string) => {
    const isSaved = profiles.some(p => p.name === name);
    if (!isSaved) {
      setSelectedProfile(null);
      return;
    }
    setIsDeleteModalOpen(true);
    setDeleteConfirmInput("");
  };

  const executeDelete = async () => {
    if (!selectedProfile) return;
    const slug = profileSlug(selectedProfile);
    setLoading(true);
    try {
      const res = await apiFetch(
        `${apiBase()}/admin/profiles/${encodeURIComponent(slug)}`,
        {
        method: "DELETE"
        }
      );
      if (!res.ok) throw new Error("Error during deletion");
      fetchProfiles();
      setSelectedProfile(null);
      setIsDeleteModalOpen(false);
      setDeleteConfirmInput("");
      setToast({ message: "Profile successfully deleted!", variant: "success" });
    } catch (e: any) {
      setToast({ message: "Deletion failed: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!selectedProfile) return;
    if (!selectedProfile.name.trim()) {
      setToast({ message: "Please enter a valid identity name before saving.", variant: "error" });
      return;
    }

    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(selectedProfile)
      });
      if (!res.ok) throw new Error("Error during save");
      fetchProfiles();
      setToast({ message: "Profile saved successfully!", variant: "success" });
    } catch (e: any) {
      setToast({ message: "Save failed: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const toggleSkill = (skill: string) => {
    setSelectedProfile((prev: any) => {
      if (!prev) return prev;
      const current = prev.skills || [];
      const isAttached = current.includes(skill);
      const updatedSkills = isAttached
        ? current.filter((s: string) => s !== skill)
        : [...current, skill];
      
      const currentCritical = prev.critical_skills ?? [];
      const updatedCritical = isAttached
        ? currentCritical.filter((s: string) => s !== skill)
        : currentCritical;

      return {
        ...prev,
        skills: updatedSkills,
        critical_skills: updatedCritical,
      };
    });
  };

  const toggleCriticalSkill = (skill: string) => {
    setSelectedProfile((prev: any) => {
      if (!prev) return prev;
      const current = prev.critical_skills ?? [];
      const updated = current.includes(skill)
        ? current.filter((s: string) => s !== skill)
        : [...current, skill];
      return { ...prev, critical_skills: updated };
    });
  };

  const toggleMCP = (mcp: string) => {
    setSelectedProfile((prev: any) => {
      if (!prev) return prev;
      const current = prev.mcp_servers || [];
      const updated = current.includes(mcp)
        ? current.filter((s: string) => s !== mcp)
        : [...current, mcp];
      return { ...prev, mcp_servers: updated };
    });
  };

  const filteredProfiles = profiles.filter((p) =>
    p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (p.description && p.description.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const filteredSkills = Object.keys(availableSkills)
    .filter(s => {
      const search = skillSearch.toLowerCase();
      const nameMatch = s.toLowerCase().includes(search);
      const skillInfo = availableSkills[s];
      const desc = skillInfo?.description || "";
      const descMatch = desc.toLowerCase().includes(search);
      const tags = skillInfo?.tags || [];
      const tagsMatch = tags.some((tag: string) => tag.toLowerCase().includes(search));
      return nameMatch || descMatch || tagsMatch;
    })
    .filter(s => !showSelectedSkillsOnly || (selectedProfile?.skills || []).includes(s))
    .sort();
  const filteredMCPs = Object.keys(availableMCPs)
    .filter(m => !NATIVE_TOOL_BUNDLES.includes(m))
    .filter(m => {
      const search = mcpSearch.toLowerCase();
      const nameMatch = m.toLowerCase().includes(search);
      const desc = availableMCPs[m] || "";
      const descMatch = desc.toLowerCase().includes(search);
      return nameMatch || descMatch;
    })
    .filter(m => !showSelectedMCPsOnly || (selectedProfile?.mcp_servers || []).includes(m));

  const handleExport = async (profile: any) => {
    if (!profile) return;
    try {
      const res = await apiFetch(
        `${apiBase()}/admin/profiles/${encodeURIComponent(profileSlug(profile))}/export`
      );
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${profile.name.toLowerCase().replace(/\s+/g, '_')}.yaml`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      setToast({ message: "Error during export: " + e.message, variant: "error" });
    }
  };

  const handleExportAll = async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles/export/all`);
      if (!res.ok) throw new Error("Global export failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `all_profiles.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      setToast({ message: "Error during global export: " + e.message, variant: "error" });
    }
  };

  const handleImport = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.yml,.yaml';
    input.onchange = async (e: any) => {
      const file = e.target.files[0];
      if (!file) return;

      const formData = new FormData();
      formData.append('file', file);

      try {
        const res = await apiFetch(`${apiBase()}/admin/profiles/import-preview`, {
          method: "POST",
          body: formData
        });
        if (!res.ok) throw new Error("Import failed");
        const data = await res.json();

        // Controllo duplicati
        const isDuplicate = profiles.some(p => p.name.toLowerCase() === data.name.toLowerCase());
        if (isDuplicate) {
          setToast({
            message: `Warning: a profile named "${data.name}" already exists. It has been loaded into the editor; clicking SAVE will overwrite the existing configuration.`,
            variant: "warning"
          });
        } else {
          setToast({ message: "YAML profile loaded into the editor. Review and save to confirm.", variant: "success" });
        }

        setSelectedProfile(data);
      } catch (err: any) {
        setToast({ message: "Error during import: " + err.message, variant: "error" });
      }
    };
    input.click();
  };

  const toggleNativeBundle = (bid: string) => {
    setSelectedProfile((prev: any) => {
      if (!prev) return prev;
      const current = prev.native_tool_groups || [];
      const updated = current.includes(bid)
        ? current.filter((s: string) => s !== bid)
        : [...current, bid];
      return { ...prev, native_tool_groups: updated };
    });
  };

  const showBelow = !!(skillTooltip && skillTooltip.y < 180);
  const showBelowMCP = !!(mcpTooltip && mcpTooltip.y < 180);

  return (
    <div className="min-h-screen w-full bg-[#050505] text-slate-200 font-sans flex flex-col">

      <div className="space-y-3 pb-4">
        <h2 className="text-3xl font-extrabold tracking-tight text-white font-sans">Agent Profiles</h2>
        <p className="text-md text-gray-400 max-w-xl mt-2 font-sans">
          Configure distinct AI agent identities, customize their system instructions, and attach specialized skills and MCP servers.
        </p>
      </div>

      {/* ==========================================
          HEADER: WORKSPACE CONTROLS & PROFILE SWITCHER
          ========================================== */}
      <header className="flex items-center justify-between px-6 py-4 bg-[#0a0a0a] border-b border-slate-800/80 sticky top-16 z-40">



        {/* Profile Switcher */}
        <HeaderDropdown
          triggerIcon={<Terminal className="w-5 h-5" />}
          triggerLabelTop="Active Identity"
          triggerLabelMain={
            loadingProfile
              ? "Loading..."
              : selectedProfile
                ? (selectedProfile.name || "New Profile")
                : "Select Profile..."
          }
          items={profiles.map((p) => ({ key: profileSlug(p), label: p.name }))}
          selectedKey={selectedProfile ? profileSlug(selectedProfile) : undefined}
          itemIcon={<Terminal className="w-4 h-4" />}
          onItemSelect={(key) => handleEdit(key)}
          searchPlaceholder="Search profiles..."
          emptyLabel="No profiles found"
          actions={[
            {
              icon: <Plus className="w-4 h-4" />,
              label: "New Profile",
              onClick: handleNewProfile,
              colorClass: "text-blue-400 hover:bg-blue-600/10",
            },
            {
              icon: <Upload className="w-4 h-4" />,
              label: "Import Profile",
              onClick: handleImport,
              colorClass: "text-emerald-400 hover:bg-emerald-600/10",
            },
          ]}
        />

        {/* Global Actions */}
        <div className="flex items-center gap-3">
          {selectedProfile && (
            <>
              {/* Export Current Profile */}
              <button
                onClick={() => handleExport(selectedProfile)}
                title="Export Current Profile"
                className="p-2.5 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
              >
                <Download className="w-5 h-5" />
              </button>

              {/* Delete Profile */}
              <button
                onClick={() => handleDelete(selectedProfile.name)}
                title="Delete Profile"
                className="p-2.5 rounded-lg text-slate-400 hover:bg-red-500/10 hover:text-red-500 transition-colors"
              >
                <Trash2 className="w-5 h-5" />
              </button>

              {/* Save Configuration */}
              <button
                onClick={handleSave}
                disabled={loading}
                className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white px-5 py-2.5 rounded-lg font-bold text-sm transition-all shadow-[0_0_15px_rgba(59,130,246,0.2)] disabled:opacity-50"
              >
                <Save className="w-4 h-4" /> {loading ? "Saving..." : "Save Configuration"}
              </button>
            </>
          )}

          {/* Export All Profiles */}
          {profiles.length > 0 && (
            <button
              onClick={handleExportAll}
              title="Export All Profiles"
              className="flex items-center gap-2 px-3 py-2 bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 rounded-lg font-semibold text-xs transition-all"
            >
              <Download className="w-3.5 h-3.5" /> Export All
            </button>
          )}
        </div>
      </header>

      {/* ==========================================
          MAIN EDITOR: LAYOUT ORIZZONTALE (2 Colonne)
          ========================================== */}
      {selectedProfile ? (
        <main className="flex-1 p-6 lg:p-10 overflow-y-auto">
          <div className="max-w-[1600px] mx-auto flex flex-col gap-6 lg:gap-8">

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12">

              {/* COLONNA TESTUALE (Prompt & Meta) */}
              <div className="lg:col-span-7 flex flex-col gap-6">

                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-wider text-slate-500">Identity Name</label>
                  <input
                    type="text"
                    value={selectedProfile.name}
                    placeholder="e.g. dev_agent"
                    onChange={(e) => setSelectedProfile((prev: any) => prev ? { ...prev, name: e.target.value } : null)}
                    className="w-full bg-[#0a0a0a] border border-slate-800 rounded-xl px-4 py-3 text-slate-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all font-medium outline-none"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-wider text-slate-500">Short Description</label>
                  <textarea
                    value={selectedProfile.description || ""}
                    placeholder="Observability-focused profile..."
                    onChange={(e) => setSelectedProfile((prev: any) => prev ? { ...prev, description: e.target.value } : null)}
                    rows={4}
                    className="w-full bg-[#0a0a0a] border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-300 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all outline-none resize-y min-h-[60px] custom-scrollbar"
                  />
                </div>

                <div className="flex-1 flex flex-col space-y-2 min-h-[600px]">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center gap-2">
                      <Terminal className="w-4 h-4" /> System Instructions (Prompt)
                    </label>
                  </div>
                  <div className="flex-1 bg-[#0a0a0a] border border-slate-800 rounded-xl p-5 text-[13px] text-slate-300 transition-all shadow-inner outline-none font-sans">
                    <BlockMarkdownEditor
                      value={selectedProfile.instructions || ""}
                      onChange={(val) => setSelectedProfile((prev: any) => prev ? { ...prev, instructions: val } : null)}
                      height={550}
                      placeholder="You are an expert AI assistant dedicated to assisting the user with specialized tasks."
                      allowTasks={false}
                    />
                  </div>
                </div>
              </div>

              {/* COLONNA CONFIGURAZIONI (Skills & Server) */}
              <div className="lg:col-span-5 flex flex-col gap-6">

                {/* Skills Panel */}
                <div className="bg-[#0a0a0a] border border-slate-800 rounded-xl p-5 flex flex-col max-h-[600px]">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <Layers className="w-4 h-4 text-blue-500" />
                      <h3 className="text-sm font-bold tracking-wider uppercase">Attached Skills</h3>
                    </div>
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => setShowSelectedSkillsOnly(!showSelectedSkillsOnly)}
                        className={`text-[10px] uppercase font-bold tracking-wider px-2 py-1 rounded-lg border transition-colors ${showSelectedSkillsOnly
                          ? 'bg-blue-500/20 text-blue-400 border-blue-500/40 hover:bg-blue-500/30'
                          : 'bg-transparent text-slate-500 border-slate-800 hover:text-slate-300 hover:border-slate-700'
                          }`}
                      >
                        {showSelectedSkillsOnly ? "Selected Only" : "Show All"}
                      </button>
                      <span className="text-[11px] text-slate-500">Click to toggle</span>
                    </div>
                  </div>

                  {/* Skill Search Box */}
                  <div className="relative mb-4">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
                    <input
                      type="text"
                      placeholder="Search available skills..."
                      value={skillSearch}
                      onChange={(e) => setSkillSearch(e.target.value)}
                      className="w-full bg-[#121212] border border-slate-800 rounded-lg pl-9 pr-8 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 outline-none transition-all"
                    />
                    {skillSearch && (
                      <button
                        onClick={() => setSkillSearch("")}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-200 transition-colors"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 overflow-y-auto pr-1 custom-scrollbar">
                    {filteredSkills.map(skill => {
                      const isAttached = (selectedProfile.skills || []).includes(skill);
                      const isCritical = (selectedProfile.critical_skills ?? []).includes(skill);

                      return (
                        <div
                          key={skill}
                          onClick={() => toggleSkill(skill)}
                          onMouseEnter={(e) => {
                            const desc = availableSkills[skill]?.description;
                            if (!desc) return;
                            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                            setSkillTooltip({
                              name: skill,
                              x: rect.left + rect.width / 2,
                              y: rect.top,
                              height: rect.height
                            });
                          }}
                          onMouseLeave={() => setSkillTooltip(null)}
                          className={`relative group flex items-center justify-between p-3 rounded-lg border cursor-pointer transition-all
                          ${isAttached
                              ? 'bg-[#121212] border-slate-700'
                              : 'bg-transparent border-slate-800 hover:border-slate-700'
                            }
                        `}
                        >
                          <span className={`text-xs font-mono truncate ${isAttached ? 'text-slate-200' : 'text-slate-500'}`}>
                            {skill}
                          </span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleCriticalSkill(skill);
                            }}
                            className="focus:outline-none p-1 -mr-1"
                          >
                            <Star className={`w-3.5 h-3.5 transition-colors ${!isAttached ? 'text-transparent' :
                              isCritical ? 'fill-amber-500 text-amber-500' : 'text-slate-600 hover:text-amber-500/50'
                              }`} />
                          </button>
                        </div>
                      );
                    })}
                    {filteredSkills.length === 0 && (
                      <div className="col-span-2 text-center text-xs text-slate-500 italic py-4">
                        No skills found
                      </div>
                    )}
                  </div>
                </div>

                {/* Connected MCP Servers & Native Tools Panel */}
                <div className="bg-[#0a0a0a] border border-slate-800 rounded-xl p-5 flex-1 flex flex-col max-h-[600px]">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-emerald-500" />
                      <h3 className="text-sm font-bold tracking-wider uppercase">Connected MCP Servers</h3>
                    </div>
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => setShowSelectedMCPsOnly(!showSelectedMCPsOnly)}
                        className={`text-[10px] uppercase font-bold tracking-wider px-2 py-1 rounded-lg border transition-colors ${showSelectedMCPsOnly
                          ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40 hover:bg-emerald-500/30'
                          : 'bg-transparent text-slate-500 border-slate-800 hover:text-slate-300 hover:border-slate-700'
                          }`}
                      >
                        {showSelectedMCPsOnly ? "Connected Only" : "Show All"}
                      </button>
                      <span className="text-[11px] text-slate-500">Click to toggle</span>
                    </div>
                  </div>

                  {/* MCP Search Box */}
                  <div className="relative mb-4">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
                    <input
                      type="text"
                      placeholder="Search servers..."
                      value={mcpSearch}
                      onChange={(e) => setMcpSearch(e.target.value)}
                      className="w-full bg-[#121212] border border-slate-800 rounded-lg pl-9 pr-8 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 outline-none transition-all"
                    />
                    {mcpSearch && (
                      <button
                        onClick={() => setMcpSearch("")}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-200 transition-colors"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>

                  <div className="space-y-4 flex-1 overflow-y-auto pr-1 custom-scrollbar">
                    {/* Native tool bundles */}
                    <div>
                      <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">Native tool bundles</h4>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {NATIVE_TOOL_BUNDLES
                          .filter(bid => !showSelectedMCPsOnly || (selectedProfile?.native_tool_groups || []).includes(bid))
                          .map((bid) => {
                            const isConnected = (selectedProfile.native_tool_groups || []).includes(bid);
                            return (
                              <div
                                key={bid}
                                onClick={() => toggleNativeBundle(bid)}
                                onMouseEnter={(e) => {
                                  const desc = availableMCPs[bid];
                                  if (!desc) return;
                                  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                                  setMcpTooltip({ name: bid, x: rect.left + rect.width / 2, y: rect.top, height: rect.height });
                                }}
                                onMouseLeave={() => setMcpTooltip(null)}
                                className={`flex items-center justify-between p-2.5 rounded-lg border cursor-pointer transition-all
                              ${isConnected
                                    ? 'bg-cyan-950/20 border-cyan-800 text-cyan-200'
                                    : 'bg-transparent border-slate-800 hover:border-slate-700 text-slate-500'
                                  }
                            `}
                              >
                                <span className="text-xs font-mono truncate">{bid}</span>
                                <span className="text-[9px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400">Native</span>
                              </div>
                            );
                          })}
                      </div>
                    </div>

                    {/* External MCP Servers */}
                    <div>
                      <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">External MCP Servers</h4>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {filteredMCPs.map((m) => {
                          const isConnected = (selectedProfile.mcp_servers || []).includes(m);
                          return (
                            <div
                              key={m}
                              onClick={() => toggleMCP(m)}
                              onMouseEnter={(e) => {
                                const desc = availableMCPs[m];
                                if (!desc) return;
                                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                                setMcpTooltip({ name: m, x: rect.left + rect.width / 2, y: rect.top, height: rect.height });
                              }}
                              onMouseLeave={() => setMcpTooltip(null)}
                              className={`flex items-center justify-between p-2.5 rounded-lg border cursor-pointer transition-all
                              ${isConnected
                                  ? 'bg-emerald-950/20 border-emerald-800 text-emerald-200'
                                  : 'bg-transparent border-slate-800 hover:border-slate-700 text-slate-500'
                                }
                            `}
                            >
                              <span className="text-xs font-mono truncate">{m}</span>
                              {isConnected && <Check className="w-3.5 h-3.5 text-emerald-400" />}
                            </div>
                          );
                        })}
                        {filteredMCPs.length === 0 && (
                          <div className="col-span-2 text-center text-xs text-slate-500 italic py-2">
                            No MCP servers found
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

              </div>

            </div>
          </div>
        </main>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-center p-12 space-y-6 min-h-[450px]">
          <div className="space-y-1 mb-6">
            <h2 className="text-3xl font-extrabold tracking-tight text-white font-sans">Agent Profiles</h2>
            <p className="text-md text-gray-400 max-w-xl mt-2 font-sans">
              Configure distinct AI agent identities, customize their system instructions, and attach specialized skills and MCP servers.
            </p>
          </div>
          <div className="w-20 h-20 rounded-2xl bg-gradient-to-tr from-blue-500/10 to-indigo-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 shadow-xl shadow-blue-500/5">
            <UserPlus className="w-10 h-10" />
          </div>
          <div className="space-y-2 max-w-sm">
            <h3 className="text-xl font-bold text-white">Select or Create an Identity</h3>
            <p className="text-sm text-slate-400 leading-relaxed">
              Choose an agent profile from the list above to configure its behavior and toolset, or create a brand new specialized identity.
            </p>
          </div>
          <button
            onClick={handleNewProfile}
            className="px-6 py-3 bg-white/10 hover:bg-white/15 border border-white/10 text-white font-semibold rounded-xl text-sm transition-all shadow-md cursor-pointer"
          >
            Create New Profile
          </button>
        </div>
      )}

      {isDeleteModalOpen && selectedProfile && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl w-full max-w-xl overflow-hidden shadow-2xl animate-in zoom-in-95 duration-200">
            <div className="p-6 border-b border-white/10 flex justify-between items-center bg-white/5">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <Trash2 className="w-5 h-5 text-red-400" />
                Confirm Deletion
              </h2>
              <button
                onClick={() => setIsDeleteModalOpen(false)}
                className="text-gray-500 hover:text-white transition-colors"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-300 text-sm leading-relaxed">
                <p className="font-semibold mb-1 text-lg flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
                  <span className="text-white font-bold">
                    WARNING: irreversible operation
                  </span>
                </p>
                You are about to permanently delete the agent profile <b className="text-white font-mono">{selectedProfile.name}</b>. This operation cannot be undone.
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-white/80 block">
                  Type the exact name (<span className="font-mono text-white font-bold">{selectedProfile.name}</span>) to confirm:
                </label>
                <input
                  type="text"
                  value={deleteConfirmInput}
                  onChange={(e) => setDeleteConfirmInput(e.target.value)}
                  placeholder={selectedProfile.name}
                  className="w-full bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-white/20 focus:outline-none focus:border-red-500/80 focus:ring-2 focus:ring-red-500/20 transition-all font-mono"
                />
              </div>
            </div>

            <div className="p-6 border-t border-white/10 flex justify-end gap-3 bg-black/20">
              <button
                onClick={() => setIsDeleteModalOpen(false)}
                className="px-5 py-2.5 text-sm font-semibold text-gray-400 hover:text-white transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={() => executeDelete()}
                disabled={deleteConfirmInput !== selectedProfile.name || loading}
                className="bg-red-600 hover:bg-red-500 text-white px-6 py-2.5 rounded-xl text-sm font-bold transition-all flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-red-600/20 cursor-pointer"
              >
                <Trash2 className="w-4 h-4" />
                {loading ? "Deleting..." : "Delete Profile"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tooltip skill — position:fixed per sfuggire all'overflow-y:auto della griglia */}
      {skillTooltip && availableSkills[skillTooltip.name] && (
        <div
          className="pointer-events-none fixed z-[9999]"
          style={{
            left: skillTooltip.x,
            top: showBelow ? (skillTooltip.y + (skillTooltip.height || 42) + 8) : (skillTooltip.y - 8),
            transform: showBelow ? 'translate(-50%, 0)' : 'translate(-50%, -100%)'
          }}
        >
          <div className="relative max-w-[300px] rounded-xl border border-white/10 bg-[#0c0c0e]/95 px-3.5 py-2.5 text-[13px] leading-relaxed text-slate-300 shadow-2xl backdrop-blur-md">
            <div>{availableSkills[skillTooltip.name]?.description}</div>
            {availableSkills[skillTooltip.name]?.tags && availableSkills[skillTooltip.name].tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1.5 pt-1.5 border-t border-white/5">
                {availableSkills[skillTooltip.name].tags.map((tag: string) => (
                  <span key={tag} className="text-[9px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-sans tracking-wide uppercase font-semibold">
                    {tag}
                  </span>
                ))}
              </div>
            )}
            {showBelow ? (
              <div className="absolute left-1/2 bottom-full -translate-x-1/2 border-4 border-transparent border-b-[#0c0c0e]/95" />
            ) : (
              <div className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-[#0c0c0e]/95" />
            )}
          </div>
        </div>
      )}

      {/* Tooltip MCP — position:fixed per sfuggire all'overflow-y:auto della griglia */}
      {mcpTooltip && availableMCPs[mcpTooltip.name] && (
        <div
          className="pointer-events-none fixed z-[9999]"
          style={{
            left: mcpTooltip.x,
            top: showBelowMCP ? (mcpTooltip.y + (mcpTooltip.height || 42) + 8) : (mcpTooltip.y - 8),
            transform: showBelowMCP ? 'translate(-50%, 0)' : 'translate(-50%, -100%)'
          }}
        >
          <div className="relative max-w-[300px] rounded-xl border border-white/10 bg-[#0c0c0e]/95 px-3.5 py-2.5 text-[13px] leading-relaxed text-slate-300 shadow-2xl backdrop-blur-md">
            {availableMCPs[mcpTooltip.name]}
            {showBelowMCP ? (
              <div className="absolute left-1/2 bottom-full -translate-x-1/2 border-4 border-transparent border-b-[#0c0c0e]/95" />
            ) : (
              <div className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-[#0c0c0e]/95" />
            )}
          </div>
        </div>
      )}

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}