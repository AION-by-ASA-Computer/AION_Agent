"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { apiFetch } from "@/lib/api/headers"
import { UserPlus, Settings2, Trash2, Save, X, Cpu, Search, Check, Plus, Layers, ShieldCheck, Sparkles, Star, ChevronRight, ChevronDown, ChevronUp, AlertTriangle, Download, Upload, Terminal, FileText, Code2, Wand2 } from "lucide-react";
import { apiBase } from "@/lib/api";
import { PageToast, ToastState } from "@/components/PageToast";
import { BlockMarkdownEditor } from "@/components/BlockMarkdownEditor";
import { HeaderDropdown } from "@/components/HeaderDropdown";
import { matchConnectorRow } from "@/lib/mcpConnectorUi";
import { type IntegrationPolicyRow } from "@/lib/mcpIntegrationPolicy";
import { oauthAdminSetupPending } from "@/lib/mcpOAuthSetup";

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
  const [registryBySlug, setRegistryBySlug] = useState<
    Record<string, { type?: string; aion_connector_id?: string; description?: string }>
  >({});
  const [integrationBySlug, setIntegrationBySlug] = useState<Record<string, IntegrationPolicyRow>>({});
  const [connectorRows, setConnectorRows] = useState<Record<string, unknown>[]>([]);
  const [skillTooltip, setSkillTooltip] = useState<{ name: string; x: number; y: number; height?: number } | null>(null);
  const [mcpTooltip, setMcpTooltip] = useState<{ name: string; x: number; y: number; height?: number } | null>(null);

  const [skillSearch, setSkillSearch] = useState("");
  const [skillDropdownOpen, setSkillDropdownOpen] = useState(false);
  const [mcpSearch, setMcpSearch] = useState("");
  const [mcpDropdownOpen, setMcpDropdownOpen] = useState(false);
  const [showSelectedSkillsOnly, setShowSelectedSkillsOnly] = useState(false);
  const [showSelectedMCPsOnly, setShowSelectedMCPsOnly] = useState(false);
  const [activeTab, setActiveTab] = useState<"identity" | "skills" | "mcp">("identity");

  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [deleteConfirmInput, setDeleteConfirmInput] = useState("");
  const [isWizardOpen, setIsWizardOpen] = useState(false);
  const [wizardPrompt, setWizardPrompt] = useState("");
  const [wizardLoading, setWizardLoading] = useState(false);
  const NATIVE_TOOL_BUNDLES = ["web_research"];

  const handleRunWizard = async () => {
    if (!wizardPrompt.trim()) return;
    setWizardLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles/wizard-generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: wizardPrompt }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Generazione wizard fallita");
      }
      const data = await res.json();
      setSelectedProfile({
        name: data.name || "Wizard Agent",
        description: data.description || "",
        instructions: data.instructions || "",
        skills: Array.isArray(data.skills) ? data.skills : [],
        critical_skills: [],
        mcp_servers: Array.isArray(data.mcp_servers) ? data.mcp_servers : [],
        native_tool_groups: [],
      });
      setIsWizardOpen(false);
      setWizardPrompt("");
      setToast({
        message: `Profilo "${data.name || "Agente"}" generato con successo! Revisiona e salva.`,
        variant: "success",
      });
    } catch (e: any) {
      setToast({ message: "Errore Wizard: " + e.message, variant: "error" });
    } finally {
      setWizardLoading(false);
    }
  };

  const [inlineRefinePrompt, setInlineRefinePrompt] = useState("");
  const [refineLoading, setRefineLoading] = useState(false);

  const handleRefineProfile = async (promptOverride?: string) => {
    const targetPrompt = promptOverride || inlineRefinePrompt;
    if (!targetPrompt.trim() || !selectedProfile) return;
    setRefineLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles/wizard-refine`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: targetPrompt,
          current_profile: selectedProfile,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Modifica profilo fallita");
      }
      const data = await res.json();
      setSelectedProfile({
        name: data.name || selectedProfile.name,
        description: data.description || selectedProfile.description,
        instructions: data.instructions || selectedProfile.instructions,
        skills: Array.isArray(data.skills) ? data.skills : selectedProfile.skills,
        critical_skills: selectedProfile.critical_skills || [],
        mcp_servers: Array.isArray(data.mcp_servers) ? data.mcp_servers : selectedProfile.mcp_servers,
        native_tool_groups: selectedProfile.native_tool_groups || [],
      });
      setInlineRefinePrompt("");
      setToast({
        message: `Profilo "${data.name || selectedProfile.name}" modificato dall'IA! Revisiona i campi sotto e salva.`,
        variant: "success",
      });
    } catch (e: any) {
      setToast({ message: "Errore Modifica AI: " + e.message, variant: "error" });
    } finally {
      setRefineLoading(false);
    }
  };

  useEffect(() => {
    fetchProfiles();
    fetchMetadata();
  }, []);

  const fetchMetadata = async () => {
    try {
      const [skillsRes, mcpRes, nativeToolsRes, integrationsRes, catalogRes] = await Promise.all([
        apiFetch(`${apiBase()}/admin/skills`),
        apiFetch(`${apiBase()}/admin/registry`),
        apiFetch(`${apiBase()}/admin/native-tools`),
        apiFetch(`${apiBase()}/admin/mcp-integrations`),
        apiFetch(`${apiBase()}/admin/mcp/connector-catalog`),
      ]);
      const skillsMap: Record<string, { description: string; tags: string[] }> = await skillsRes.json();
      const mcp: Record<string, any> = await mcpRes.json();
      const nativeTools = await nativeToolsRes.json();
      const mcpMap: Record<string, string> = {};
      const registryMap: typeof registryBySlug = {};
      for (const [key, cfg] of Object.entries(mcp)) {
        const row = cfg as { description?: string; type?: string; aion_connector_id?: string };
        mcpMap[key] = row?.description || "";
        registryMap[key] = row;
      }
      if (nativeTools && nativeTools.bundles) {
        for (const [key, bundle] of Object.entries(nativeTools.bundles)) {
          mcpMap[key] = (bundle as any)?.description || "";
        }
      }
      if (integrationsRes.ok) {
        const integrationsData = await integrationsRes.json();
        const policyMap: Record<string, IntegrationPolicyRow> = {};
        for (const row of (integrationsData.integrations || []) as IntegrationPolicyRow[]) {
          policyMap[row.server_slug] = row;
        }
        setIntegrationBySlug(policyMap);
      }
      if (catalogRes.ok) {
        const catalogData = await catalogRes.json();
        setConnectorRows(Array.isArray(catalogData.connectors) ? catalogData.connectors : []);
      }
      setAvailableSkills(skillsMap);
      setAvailableMCPs(mcpMap);
      setRegistryBySlug(registryMap);
    } catch (e) {
      console.error("Failed to fetch available metadata", e);
    }
  };

  const mcpAwaitingAdminSetup = useCallback(
    (slug: string) => {
      const cfg = registryBySlug[slug];
      const policy = integrationBySlug[slug];
      const connector = matchConnectorRow(
        slug,
        cfg?.aion_connector_id || policy?.aion_connector_id || undefined,
        connectorRows,
      );
      return oauthAdminSetupPending(policy?.oauth_config, connector, cfg);
    },
    [registryBySlug, integrationBySlug, connectorRows],
  );

  const fetchProfiles = async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles`);
      if (!res.ok) throw new Error("Error loading profiles");
      const data = await res.json();
      setProfiles(data);
      if (data.length > 0 && !selectedProfile) {
        const lastSlug = typeof window !== "undefined" ? localStorage.getItem("aion_last_selected_profile") : null;
        const exists = lastSlug ? data.some((p: any) => profileSlug(p) === lastSlug) : false;
        const targetSlug = exists ? lastSlug : profileSlug(data[0]);

        const detailRes = await apiFetch(
          `${apiBase()}/admin/profiles/${encodeURIComponent(targetSlug as string)}`
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
      if (typeof window !== "undefined" && slug) {
        localStorage.setItem("aion_last_selected_profile", slug);
      }
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
      if (typeof window !== "undefined") {
        localStorage.removeItem("aion_last_selected_profile");
      }
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
      const blockedMcps = (selectedProfile.mcp_servers || []).filter((slug: string) =>
        mcpAwaitingAdminSetup(slug),
      );
      const payload = { ...selectedProfile };
      if (blockedMcps.length > 0) {
        payload.mcp_servers = (selectedProfile.mcp_servers || []).filter(
          (slug: string) => !mcpAwaitingAdminSetup(slug),
        );
      }

      const res = await apiFetch(`${apiBase()}/admin/profiles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error("Error during save");

      const resData = await res.json();
      const savedSlug = resData.slug || profileSlug(selectedProfile);

      if (typeof window !== "undefined") {
        localStorage.setItem("aion_last_selected_profile", savedSlug);
      }

      if (blockedMcps.length > 0) {
        setToast({
          message: `Profilo salvato. Rimossi MCP non configurati: ${blockedMcps.join(", ")}. Completa OAuth in MCP Hub.`,
          variant: "warning",
        });
      } else {
        setToast({ message: "Profile saved successfully!", variant: "success" });
      }

      await fetchProfiles();
      await handleEdit(savedSlug);
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
    const isConnected = (selectedProfile?.mcp_servers || []).includes(mcp);
    if (mcpAwaitingAdminSetup(mcp) && !isConnected) {
      setToast({
        message:
          "Questo MCP è in attesa di configurazione OAuth in MCP Hub (client ID/secret). Completa la configurazione prima di collegarlo a un profilo.",
        variant: "warning",
      });
      return;
    }
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
    .filter(m => {
      if (mcpAwaitingAdminSetup(m)) {
        return (selectedProfile?.mcp_servers || []).includes(m);
      }
      return true;
    })
    .filter(m => !showSelectedMCPsOnly || (selectedProfile?.mcp_servers || []).includes(m));

  const profileHasBlockedMcps = useMemo(
    () => (selectedProfile?.mcp_servers || []).some((slug: string) => mcpAwaitingAdminSetup(slug)),
    [selectedProfile?.mcp_servers, mcpAwaitingAdminSetup],
  );

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
          HEADER: WORKSPACE CONTROLS & PROFILE SWITCHER & TAB NAVIGATION
          ========================================== */}
      <header className="flex flex-col gap-3 px-6 py-4 bg-[#0a0a0a]/95 border border-slate-800/80 sticky top-16 z-40 backdrop-blur-xl shadow-2xl rounded-2xl mb-6">
        <div className="flex items-center justify-between gap-4 flex-wrap">
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
                icon: <Wand2 className="w-4 h-4" />,
                label: "AI Wizard Generator",
                onClick: () => setIsWizardOpen(true),
                colorClass: "text-purple-400 hover:bg-purple-600/10 font-bold",
              },
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
        </div>

        {/* Section Tabs Navigation inside the sticky Header container */}
        {selectedProfile && (
          <div className="pt-3 border-t border-slate-800/80 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={() => setActiveTab("identity")}
                className={`flex items-center gap-2.5 px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-wider transition-all cursor-pointer ${activeTab === "identity"
                  ? "bg-gradient-to-r from-purple-600 via-indigo-600 to-blue-600 text-white shadow-lg shadow-purple-900/40"
                  : "text-slate-400 hover:text-white hover:bg-white/5"
                  }`}
              >
                <UserPlus className="w-4 h-4" />
                <span>1. Identity & Instructions</span>
              </button>

              <button
                type="button"
                onClick={() => setActiveTab("skills")}
                className={`flex items-center gap-2.5 px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-wider transition-all cursor-pointer ${activeTab === "skills"
                  ? "bg-gradient-to-r from-blue-600 via-cyan-600 to-teal-600 text-white shadow-lg shadow-blue-900/40"
                  : "text-slate-400 hover:text-white hover:bg-white/5"
                  }`}
              >
                <Layers className="w-4 h-4" />
                <span>2. Capability Skills</span>
                <span className="px-2 py-0.5 rounded-full bg-white/20 text-[10px] font-mono text-white">
                  {(selectedProfile.skills || []).length}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setActiveTab("mcp")}
                className={`flex items-center gap-2.5 px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-wider transition-all cursor-pointer ${activeTab === "mcp"
                  ? "bg-gradient-to-r from-emerald-600 via-teal-600 to-green-600 text-white shadow-lg shadow-emerald-900/40"
                  : "text-slate-400 hover:text-white hover:bg-white/5"
                  }`}
              >
                <Cpu className="w-4 h-4" />
                <span>3. MCP Tools & Servers</span>
                <span className="px-2 py-0.5 rounded-full bg-white/20 text-[10px] font-mono text-white">
                  {(selectedProfile.mcp_servers || []).length}
                </span>
              </button>
            </div>

            <div className="hidden md:flex items-center gap-3 pr-2">
              <span className="text-xs text-slate-400 font-mono">
                Agent: <strong className="text-purple-400 font-semibold">{selectedProfile.name || "Untitled"}</strong>
              </span>
            </div>
          </div>
        )}
      </header>

      {/* ==========================================
          MAIN EDITOR: LAYOUT ORIZZONTALE (2 Colonne)
          ========================================== */}
      {selectedProfile ? (
        <main className="flex-1">
          <div className="max-w-[1600px] mx-auto flex flex-col gap-6">

            {/* ================= TAB 1: IDENTITY & INSTRUCTIONS ================= */}
            {activeTab === "identity" && (
              <div className="flex flex-col gap-6 animate-in fade-in duration-200">

                {/* ELEGANT COMPACT TOP BANNER: AI PROFILE CO-PILOT */}
                <div className="rounded-2xl border border-purple-500/30 bg-gradient-to-r from-purple-950/40 via-[#121216] to-indigo-950/40 p-3.5 px-5 flex flex-col md:flex-row md:items-center justify-between gap-3 shadow-2xl backdrop-blur-md">
                  <div className="flex items-center gap-2 text-purple-400 font-bold text-xs uppercase tracking-wider shrink-0">
                    <Wand2 className="w-4 h-4 animate-pulse" />
                    <span>AI Profile Co-Pilot</span>
                  </div>

                  <div className="flex-1 flex items-center gap-2 max-w-3xl">
                    <input
                      type="text"
                      value={inlineRefinePrompt}
                      onChange={(e) => setInlineRefinePrompt(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleRefineProfile();
                      }}
                      placeholder="Chiedi all'IA di modificare questo profilo... (es: 'Formatta in JSON', 'Aggiungi memoria LTM')"
                      className="flex-1 bg-black/60 border border-purple-500/30 rounded-xl px-4 py-2 text-xs text-white placeholder:text-gray-500 focus:border-purple-500 focus:ring-1 focus:ring-purple-500/30 outline-none transition-all"
                    />
                    <button
                      type="button"
                      onClick={() => handleRefineProfile()}
                      disabled={refineLoading || !inlineRefinePrompt.trim()}
                      className="flex items-center gap-2 px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs shadow-md shadow-purple-900/30 disabled:opacity-50 transition-all cursor-pointer whitespace-nowrap"
                    >
                      {refineLoading ? (
                        <>
                          <Sparkles className="w-3.5 h-3.5 animate-spin" />
                          <span>...</span>
                        </>
                      ) : (
                        <>
                          <Wand2 className="w-3.5 h-3.5" />
                          <span>Applica</span>
                        </>
                      )}
                    </button>
                  </div>

                  <div className="hidden lg:flex items-center gap-1.5 shrink-0">
                    {[
                      { label: "🧠 Memoria", prompt: "Aggiungi la capacità di ricordare conversazioni passate con la memoria a lungo termine, aggiungendo l'MCP \"Mnemos\" e la skill \"memory_protocol\"." },
                      { label: "📧 Email", prompt: "Aggiungi l'integrazione per leggere ed inviare email via IMAP/SMTP." },
                      { label: "🌐 Web", prompt: "Aggiungi la capacità di effettuare ricerche sul web." },
                      { label: "⚡ JSON", prompt: "Aggiorna le istruzioni rendendo obbligatorio il formato JSON strutturato per tutte le risposte." },
                    ].map((chip) => (
                      <button
                        key={chip.label}
                        type="button"
                        onClick={() => handleRefineProfile(chip.prompt)}
                        disabled={refineLoading}
                        className="px-2.5 py-1 rounded-lg bg-purple-900/30 border border-purple-500/25 text-purple-300 hover:bg-purple-800/50 hover:border-purple-400 text-xs transition-all cursor-pointer font-medium disabled:opacity-50"
                      >
                        {chip.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* TOP ROW (2 EQUAL COLUMNS): AGENT IDENTITY (LEFT 6 COLS) vs CONFIGURED TOOLS (RIGHT 6 COLS) */}
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">

                  {/* LEFT (6 COLS): Agent Identity Metadata Card */}
                  <div className="lg:col-span-6 bg-[#0e0e12] border border-white/10 rounded-2xl p-5 flex flex-col justify-between shadow-2xl">
                    <div className="flex items-center gap-2 text-indigo-400 font-bold text-xs uppercase tracking-wider pb-2 border-b border-white/5">
                      <UserPlus className="w-4 h-4" />
                      <span>Agent Identity</span>
                    </div>

                    <div className="flex flex-col gap-4 py-3">
                      <div className="space-y-1.5">
                        <label className="text-xs font-bold uppercase tracking-wider text-slate-400">
                          Identity Name <span className="text-red-400">*</span>
                        </label>
                        <input
                          type="text"
                          value={selectedProfile.name}
                          placeholder="e.g. dev_agent"
                          onChange={(e) => setSelectedProfile((prev: any) => prev ? { ...prev, name: e.target.value } : null)}
                          className="w-full bg-[#16161d] border border-white/10 rounded-xl px-4 py-2.5 text-slate-100 font-bold focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all outline-none text-sm"
                        />
                      </div>

                      <div className="space-y-1.5">
                        <label className="text-xs font-bold uppercase tracking-wider text-slate-400">
                          Short Description
                        </label>
                        <textarea
                          value={selectedProfile.description || ""}
                          placeholder="Observability-focused profile..."
                          onChange={(e) => setSelectedProfile((prev: any) => prev ? { ...prev, description: e.target.value } : null)}
                          rows={2}
                          className="w-full bg-[#16161d] border border-white/10 rounded-xl px-4 py-2.5 text-xs text-slate-300 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all outline-none resize-none custom-scrollbar min-h-[60px]"
                        />
                      </div>
                    </div>
                  </div>

                  {/* RIGHT (6 COLS): Configured Tools & Capabilities Summary Card */}
                  <div className="lg:col-span-6 bg-[#0e0e12] border border-white/10 rounded-2xl p-5 flex flex-col justify-between shadow-2xl">
                    <div className="text-xs font-bold uppercase tracking-wider text-slate-300 pb-2 border-b border-white/5 flex items-center gap-2">
                      <Layers className="w-4 h-4 text-cyan-400" />
                      <span>Configured Tools & Capabilities</span>
                    </div>

                    <div className="flex flex-col gap-3 py-3">
                      <div className="flex items-center justify-between p-3.5 rounded-xl bg-blue-950/25 border border-blue-500/30 shadow-sm">
                        <div className="flex items-center gap-3">
                          <Layers className="w-5 h-5 text-blue-400" />
                          <div>
                            <div className="text-sm font-bold text-slate-100">Attached Capability Skills</div>
                            <div className="text-xs text-slate-400 font-mono">{(selectedProfile.skills || []).length} active skills attached</div>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => setActiveTab("skills")}
                          className="px-4 py-2 rounded-xl bg-blue-600/30 border border-blue-500/40 text-blue-200 hover:bg-blue-600/50 text-xs font-bold transition-all cursor-pointer shadow-sm"
                        >
                          Manage →
                        </button>
                      </div>

                      <div className="flex items-center justify-between p-3.5 rounded-xl bg-emerald-950/25 border border-emerald-500/30 shadow-sm">
                        <div className="flex items-center gap-3">
                          <Cpu className="w-5 h-5 text-emerald-400" />
                          <div>
                            <div className="text-sm font-bold text-slate-100">Connected MCP Servers</div>
                            <div className="text-xs text-slate-400 font-mono">{(selectedProfile.mcp_servers || []).length} servers connected</div>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => setActiveTab("mcp")}
                          className="px-4 py-2 rounded-xl bg-emerald-600/30 border border-emerald-500/40 text-emerald-200 hover:bg-emerald-600/50 text-xs font-bold transition-all cursor-pointer shadow-sm"
                        >
                          Manage →
                        </button>
                      </div>
                    </div>
                  </div>

                </div>

                {/* BOTTOM ROW (FULL WIDTH): SYSTEM INSTRUCTIONS PROMPT EDITOR (EXACTLY LIKE SKILLS PAGE!) */}
                <div className="flex-1 flex flex-col space-y-3 min-h-[550px]">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                      <Terminal className="w-4 h-4 text-indigo-400" />
                      <span>System Instructions (Prompt)</span>
                    </label>
                    <span className="text-xs text-slate-400 font-mono">Full-width Markdown Editor</span>
                  </div>
                  <div className="flex-1 bg-[#0e0e12] border border-white/10 rounded-2xl p-5 text-sm text-slate-200 transition-all shadow-2xl">
                    <BlockMarkdownEditor
                      value={selectedProfile.instructions || ""}
                      onChange={(val) => setSelectedProfile((prev: any) => prev ? { ...prev, instructions: val } : null)}
                      height={500}
                      placeholder="You are an expert AI assistant dedicated to assisting the user with specialized tasks."
                      allowTasks={false}
                    />
                  </div>
                </div>

              </div>
            )}

            {/* ================= TAB 2: CAPABILITY SKILLS ================= */}
            {activeTab === "skills" && (
              <div className="flex flex-col gap-6 animate-in fade-in duration-200">
                <div className="bg-[#0e0e12] border border-white/10 rounded-2xl p-6 shadow-2xl flex flex-col min-h-[600px]">

                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6 pb-4 border-b border-white/5">
                    <div>
                      <h3 className="text-xl font-extrabold text-white flex items-center gap-2.5">
                        <Layers className="w-6 h-6 text-blue-400" />
                        <span>Attached Capability Skills</span>
                      </h3>
                      <p className="text-sm text-slate-300 mt-1">
                        Select skills to attach to this profile. Attached skills provide specialized execution protocols and workflows.
                      </p>
                    </div>

                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => setShowSelectedSkillsOnly(!showSelectedSkillsOnly)}
                        className={`text-xs uppercase font-bold tracking-wider px-4 py-2 rounded-xl border transition-all cursor-pointer ${showSelectedSkillsOnly
                          ? 'bg-blue-500/20 text-blue-300 border-blue-500/40 shadow-lg shadow-blue-900/20'
                          : 'bg-white/5 text-slate-300 border-white/10 hover:text-white hover:bg-white/10'
                          }`}
                      >
                        {showSelectedSkillsOnly ? "Attached Only" : "Show All Skills"}
                      </button>
                    </div>
                  </div>

                  {/* Skill Search Box */}
                  <div className="relative mb-6">
                    <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                    <input
                      type="text"
                      placeholder="Search available skills by name, tag, or description..."
                      value={skillSearch}
                      onChange={(e) => setSkillSearch(e.target.value)}
                      className="w-full bg-[#16161d] border border-white/10 rounded-xl pl-11 pr-10 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-all font-medium"
                    />
                    {skillSearch && (
                      <button
                        onClick={() => setSkillSearch("")}
                        className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 transition-colors"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    )}
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 flex-1 overflow-y-auto pr-1 custom-scrollbar">
                    {filteredSkills.map((skill) => {
                      const isAttached = (selectedProfile.skills || []).includes(skill);
                      const isCritical = (selectedProfile.critical_skills ?? []).includes(skill);
                      const skillInfo = availableSkills[skill];

                      return (
                        <div
                          key={skill}
                          onClick={() => toggleSkill(skill)}
                          className={`group relative flex flex-col justify-between p-5 rounded-2xl border cursor-pointer transition-all ${isAttached
                            ? 'bg-blue-950/30 border-blue-500/60 shadow-xl shadow-blue-950/40 text-white'
                            : 'bg-[#16161d]/60 border-white/10 hover:border-white/25 hover:bg-[#16161d] text-slate-300'
                            }`}
                        >
                          <div className="space-y-3">
                            <div className="flex items-center justify-between gap-2">
                              <span className={`text-sm font-mono font-bold truncate ${isAttached ? 'text-blue-300' : 'text-slate-100'}`}>
                                {skill}
                              </span>
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  toggleCriticalSkill(skill);
                                }}
                                className="focus:outline-none p-1"
                                title={isCritical ? "Skill critica (sempre abilitata)" : "Segna come skill critica"}
                              >
                                <Star className={`w-4 h-4 transition-colors ${!isAttached ? 'text-transparent' : isCritical ? 'fill-amber-400 text-amber-400' : 'text-slate-500 hover:text-amber-400/80'}`} />
                              </button>
                            </div>

                            <p className="text-xs text-slate-300 line-clamp-3 leading-relaxed font-sans">
                              {skillInfo?.description || "Specialized competence protocol file."}
                            </p>
                          </div>

                          <div className="flex items-center justify-between pt-4 mt-3 border-t border-white/10">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {(skillInfo?.tags || []).slice(0, 3).map((t) => (
                                <span key={t} className="px-2 py-0.5 rounded-md bg-white/10 text-xs font-mono text-slate-300 font-medium">
                                  #{t}
                                </span>
                              ))}
                            </div>

                            <span className={`text-xs font-bold uppercase tracking-wider px-3 py-1 rounded-full shadow-sm ${isAttached ? 'bg-blue-500/30 text-blue-200 border border-blue-400/40' : 'bg-white/5 text-slate-400 border border-white/5'
                              }`}>
                              {isAttached ? 'Attached' : 'Off'}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                    {filteredSkills.length === 0 && (
                      <div className="col-span-full text-center text-sm text-slate-400 italic py-12">
                        No skills found matching your search.
                      </div>
                    )}
                  </div>

                </div>
              </div>
            )}

            {/* ================= TAB 3: CONNECTED MCP SERVERS ================= */}
            {activeTab === "mcp" && (
              <div className="flex flex-col gap-6 animate-in fade-in duration-200">
                <div className="bg-[#0e0e12] border border-white/10 rounded-2xl p-6 shadow-2xl flex flex-col min-h-[600px]">

                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6 pb-4 border-b border-white/5">
                    <div>
                      <h3 className="text-xl font-extrabold text-white flex items-center gap-2.5">
                        <Cpu className="w-6 h-6 text-emerald-400" />
                        <span>Connected MCP Servers & Native Tools</span>
                      </h3>
                      <p className="text-sm text-slate-300 mt-1">
                        Attach Model Context Protocol (MCP) servers and native tool bundles to expand the agent's tool execution capabilities.
                      </p>
                    </div>

                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => setShowSelectedMCPsOnly(!showSelectedMCPsOnly)}
                        className={`text-xs uppercase font-bold tracking-wider px-4 py-2 rounded-xl border transition-all cursor-pointer ${showSelectedMCPsOnly
                          ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-lg shadow-emerald-950/20'
                          : 'bg-white/5 text-slate-300 border-white/10 hover:text-white hover:bg-white/10'
                          }`}
                      >
                        {showSelectedMCPsOnly ? "Connected Only" : "Show All MCPs"}
                      </button>
                    </div>
                  </div>

                  {profileHasBlockedMcps ? (
                    <div className="mb-5 flex items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-xs text-amber-200 shadow-lg">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                      <span>
                        Alcuni MCP collegati sono in attesa di configurazione OAuth in MCP Hub. Rimuovili dal profilo o completa client ID/secret prima di usarli in chat.
                      </span>
                    </div>
                  ) : null}

                  {/* MCP Search Box */}
                  <div className="relative mb-6">
                    <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                    <input
                      type="text"
                      placeholder="Search available MCP servers or native tools..."
                      value={mcpSearch}
                      onChange={(e) => setMcpSearch(e.target.value)}
                      className="w-full bg-[#16161d] border border-white/10 rounded-xl pl-11 pr-10 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none transition-all font-medium"
                    />
                    {mcpSearch && (
                      <button
                        onClick={() => setMcpSearch("")}
                        className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 transition-colors"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    )}
                  </div>

                  <div className="space-y-6 flex-1 overflow-y-auto pr-1 custom-scrollbar">

                    {/* Native tool bundles */}
                    <div>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-300 mb-3 flex items-center gap-2">
                        <Code2 className="w-4 h-4 text-cyan-400" />
                        <span>Native Tool Bundles</span>
                      </h4>
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                        {NATIVE_TOOL_BUNDLES
                          .filter(bid => !showSelectedMCPsOnly || (selectedProfile?.native_tool_groups || []).includes(bid))
                          .map((bid) => {
                            const isConnected = (selectedProfile.native_tool_groups || []).includes(bid);
                            return (
                              <div
                                key={bid}
                                onClick={() => toggleNativeBundle(bid)}
                                className={`flex items-center justify-between p-5 rounded-2xl border cursor-pointer transition-all ${isConnected
                                  ? 'bg-cyan-950/30 border-cyan-500/60 shadow-xl shadow-cyan-950/40 text-cyan-100'
                                  : 'bg-[#16161d]/60 border-white/10 hover:border-white/25 hover:bg-[#16161d] text-slate-300'
                                  }`}
                              >
                                <div>
                                  <div className="text-sm font-mono font-bold text-slate-100">{bid}</div>
                                  <div className="text-xs text-slate-300 mt-1">Built-in agent execution tools</div>
                                </div>
                                <span className="text-xs uppercase font-bold tracking-wider px-2.5 py-1 rounded-md bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                                  Native
                                </span>
                              </div>
                            );
                          })}
                      </div>
                    </div>

                    {/* External MCP Servers */}
                    <div>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-300 mb-3 flex items-center gap-2">
                        <Cpu className="w-4 h-4 text-emerald-400" />
                        <span>External MCP Servers</span>
                      </h4>
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                        {filteredMCPs.map((m) => {
                          const isConnected = (selectedProfile.mcp_servers || []).includes(m);
                          const awaitingSetup = mcpAwaitingAdminSetup(m);
                          const mcpDesc = availableMCPs[m];

                          return (
                            <div
                              key={m}
                              onClick={() => toggleMCP(m)}
                              className={`flex flex-col justify-between p-5 rounded-2xl border transition-all ${awaitingSetup
                                ? isConnected
                                  ? "cursor-pointer border-amber-700/60 bg-amber-950/20 text-amber-200"
                                  : "cursor-not-allowed border-slate-800/80 bg-slate-900/40 text-slate-600 opacity-60"
                                : "cursor-pointer"
                                } ${!awaitingSetup && isConnected
                                  ? "bg-emerald-950/30 border-emerald-500/60 shadow-xl shadow-emerald-950/40 text-emerald-100"
                                  : !awaitingSetup
                                    ? "bg-[#16161d]/60 border-white/10 hover:border-white/25 hover:bg-[#16161d] text-slate-300"
                                    : ""
                                }`}
                            >
                              <div className="space-y-2">
                                <div className="flex items-center justify-between gap-2">
                                  <span className="text-sm font-mono font-bold text-slate-100 truncate">{m}</span>
                                  {isConnected && <Check className="h-4 w-4 text-emerald-400" />}
                                </div>
                                <p className="text-xs text-slate-300 line-clamp-3 leading-relaxed font-sans">
                                  {mcpDesc || "External MCP integration server"}
                                </p>
                              </div>

                              <div className="pt-4 mt-3 border-t border-white/10 flex items-center justify-between">
                                <span className={`text-xs font-bold uppercase tracking-wider px-3 py-1 rounded-full shadow-sm ${isConnected ? 'bg-emerald-500/30 text-emerald-200 border border-emerald-400/40' : 'bg-white/5 text-slate-400 border border-white/5'
                                  }`}>
                                  {isConnected ? 'Connected' : 'Disconnected'}
                                </span>
                                {awaitingSetup && (
                                  <span className="text-xs font-bold text-amber-400">Attesa OAuth</span>
                                )}
                              </div>
                            </div>
                          );
                        })}
                        {filteredMCPs.length === 0 && (
                          <div className="col-span-full text-center text-sm text-slate-400 italic py-8">
                            No MCP servers found.
                          </div>
                        )}
                      </div>
                    </div>

                  </div>

                </div>
              </div>
            )}

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

      {/* AI PROFILE WIZARD MODAL */}
      {isWizardOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200">
          <div className="w-full max-w-xl rounded-2xl bg-[#121212] border border-purple-500/40 p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <div className="flex items-center gap-2 text-purple-400 font-bold text-lg">
                <Wand2 className="w-5 h-5 animate-pulse" />
                <span>AI Profile Creation Wizard</span>
              </div>
              <button
                onClick={() => setIsWizardOpen(false)}
                className="text-gray-400 hover:text-white p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-gray-400 leading-relaxed">
              Descrivi l'agente desiderato in linguaggio naturale. Il sistema selezionerà automaticamente dal catalogo le Skill ed i server MCP adatti, garantendo l'inclusione di tutte le skill e MCP necessarie all'agente per lo scopo che stai descrivendo. Tutte le istruzioni dell'agente verranno generate rigorosamente in <b className="text-white">Inglese</b>.
            </p>

            {/* QUICK SUGGESTION CHIPS */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
                💡 Suggerimenti per arricchire il prompt:
              </label>
              <div className="flex flex-wrap gap-2">
                {[
                  { label: "🧠 Memoria a Lungo Termine", add: " Includi la capacità di ricordare conversazioni passate con la memoria a lungo termine." },
                  { label: "📧 Lettura & Invio Email", add: " Aggiungi l'integrazione per leggere e gestire email via IMAP." },
                  { label: "🌐 Ricerca Web Avanzata", add: " Aggiungi le funzionalità di ricerca e scraping web." },
                  { label: "🗄️ Query Database SQL", add: " Includi l'accesso per interrogare schemi e tabelle di database SQL." },
                  { label: "📄 Analisi OCR & Documenti", add: " Abilita l'estrazione di testo da immagini e file PDF/OCR." },
                ].map((chip) => (
                  <button
                    key={chip.label}
                    type="button"
                    onClick={() => {
                      if (!wizardPrompt.includes(chip.add.trim())) {
                        setWizardPrompt((prev) => (prev ? prev + chip.add : chip.add.trim()));
                      }
                    }}
                    className="px-2.5 py-1 rounded-lg bg-purple-950/40 border border-purple-500/30 text-purple-300 hover:bg-purple-900/60 hover:border-purple-400 text-xs transition-all cursor-pointer font-medium"
                  >
                    {chip.label}
                  </button>
                ))}
              </div>
            </div>

            <textarea
              rows={4}
              value={wizardPrompt}
              onChange={(e) => setWizardPrompt(e.target.value)}
              placeholder="Es: Voglio un agente per il supporto clienti che consulti la documentazione interna e risponda ai ticket Jira..."
              className="w-full bg-black/60 border border-white/10 rounded-xl p-3.5 text-sm text-white placeholder:text-gray-600 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 outline-none resize-none"
            />

            <div className="flex items-center justify-between pt-1">
              <span className="text-[11px] text-gray-500 italic">
                Output generato in Inglese (LLM Native)
              </span>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setIsWizardOpen(false)}
                  className="px-4 py-2 text-xs font-semibold text-gray-400 hover:text-white"
                >
                  Annulla
                </button>
                <button
                  onClick={handleRunWizard}
                  disabled={wizardLoading || !wizardPrompt.trim()}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs shadow-lg disabled:opacity-50 transition-all cursor-pointer shadow-purple-900/30"
                >
                  {wizardLoading ? (
                    <>
                      <Sparkles className="w-4 h-4 animate-spin" />
                      <span>Generazione Profilo (EN)...</span>
                    </>
                  ) : (
                    <>
                      <Wand2 className="w-4 h-4" />
                      <span>Genera Profilo con IA</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}