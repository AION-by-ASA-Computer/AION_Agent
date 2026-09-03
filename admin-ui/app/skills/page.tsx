"use client";

import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { Save, Plus, FileCode, X, Trash2, AlertTriangle, Download, Upload, Wand2, Sparkles } from "lucide-react";
import { PageToast, ToastState } from "@/components/PageToast";
import { BlockMarkdownEditor } from "@/components/BlockMarkdownEditor";
import { HeaderDropdown } from "@/components/HeaderDropdown";

type SkillSummary = {
  description?: string;
  tags?: string[];
  status?: string;
  source?: string;
  view_count?: number;
};

export default function SkillsPage() {
  const [skills, setSkills] = useState<string[]>([]);
  const [skillMeta, setSkillMeta] = useState<Record<string, SkillSummary>>({});
  const [statusFilter, setStatusFilter] = useState<"" | "draft" | "verified">("");
  const [selectedSkill, setSelectedSkill] = useState<{ name: string; content: string; metadata?: Record<string, any> } | null>(null);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<ToastState>(null);
  const [tagInput, setTagInput] = useState("");

  const [isWizardOpen, setIsWizardOpen] = useState(false);
  const [wizardPrompt, setWizardPrompt] = useState("");
  const [wizardLoading, setWizardLoading] = useState(false);

  const handleRunWizard = async () => {
    if (!wizardPrompt.trim()) return;
    setWizardLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/skills/wizard-generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: wizardPrompt }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Generazione skill wizard fallita");
      }
      const data = await res.json();
      setSelectedSkill({
        name: data.name || "custom_skill",
        content: data.content || "",
        metadata: {
          description: data.description || "",
          tags: Array.isArray(data.tags) ? data.tags : [],
          status: data.status || "draft",
        },
      });
      setTagInput(Array.isArray(data.tags) ? data.tags.join(", ") : "");
      setIsWizardOpen(false);
      setWizardPrompt("");
      setToast({
        message: `Skill "${data.name || "skill"}" generata con successo! Revisiona e salva.`,
        variant: "success",
      });
    } catch (e: any) {
      setToast({ message: "Errore Skill Wizard: " + e.message, variant: "error" });
    } finally {
      setWizardLoading(false);
    }
  };

  const [inlineRefinePrompt, setInlineRefinePrompt] = useState("");
  const [refineLoading, setRefineLoading] = useState(false);

  const handleRefineSkill = async (promptOverride?: string) => {
    const targetPrompt = promptOverride || inlineRefinePrompt;
    if (!targetPrompt.trim() || !selectedSkill) return;
    setRefineLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/skills/wizard-refine`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: targetPrompt,
          current_skill: selectedSkill,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Modifica skill fallita");
      }
      const data = await res.json();
      setSelectedSkill({
        name: data.name || selectedSkill.name,
        content: data.content || selectedSkill.content,
        metadata: {
          description: data.description || selectedSkill.metadata?.description || "",
          tags: Array.isArray(data.tags) ? data.tags : selectedSkill.metadata?.tags || [],
          status: data.status || selectedSkill.metadata?.status || "draft",
        },
      });
      setTagInput(Array.isArray(data.tags) ? data.tags.join(", ") : "");
      setInlineRefinePrompt("");
      setToast({
        message: `Skill "${data.name || selectedSkill.name}" modificata dall'IA! Revisiona ed effettua il salvataggio.`,
        variant: "success",
      });
    } catch (e: any) {
      setToast({ message: "Errore Modifica AI Skill: " + e.message, variant: "error" });
    } finally {
      setRefineLoading(false);
    }
  };

  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [deleteConfirmInput, setDeleteConfirmInput] = useState("");

  const [isBlockedModalOpen, setIsBlockedModalOpen] = useState(false);
  const [blockingProfiles, setBlockingProfiles] = useState<string[]>([]);

  useEffect(() => {
    fetchSkills();
  }, [statusFilter]);

  const handlePromote = async (name: string) => {
    if (!name) return;
    setLoading(true);
    try {
      const res = await apiFetch(
        `${apiBase()}/admin/skills/${encodeURIComponent(name)}/promote`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error("Promote failed");
      await fetchSkills();
      setToast({ message: `Skill "${name}" promoted to verified.`, variant: "success" });
    } catch (e: any) {
      setToast({ message: "Promote failed: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const fetchSkills = async () => {
    try {
      const qs = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
      const res = await apiFetch(`${apiBase()}/admin/skills${qs}`);
      if (!res.ok) throw new Error("Error loading skills");
      const data: Record<string, SkillSummary> = await res.json();
      setSkillMeta(data);
      const names = Object.keys(data).sort();
      setSkills(names);
      if (names.length > 0 && !selectedSkill) {
        // Automatically fetch details for the first skill in the list
        const detailRes = await apiFetch(
          `${apiBase()}/admin/skills/${encodeURIComponent(names[0])}`
        );
        if (detailRes.ok) {
          const detailData = await detailRes.json();
          setSelectedSkill(detailData);
          setTagInput((detailData.metadata?.tags || []).join(", "));
        }
      }
    } catch (e: any) {
      console.error(e);
      setToast({ message: "Could not connect to backend: " + e.message, variant: "error" });
    }
  };

  const handleEdit = async (name: string) => {
    try {
      const res = await apiFetch(
        `${apiBase()}/admin/skills/${encodeURIComponent(name)}`
      );
      if (!res.ok) throw new Error("Error loading skill");
      const data = await res.json();
      setSelectedSkill(data);
      setTagInput((data.metadata?.tags || []).join(", "));
    } catch (e: any) {
      setToast({ message: "Error loading skill: " + e.message, variant: "error" });
    }
  };

  const handleNewSkill = () => {
    setTagInput("");
    setSelectedSkill({
      name: "",
      content: "# New Protocol\n\nDescribe the specialized agent protocol here...\n",
      metadata: { description: "", tags: [] },
    });
  };



  const handleSave = async () => {
    if (!selectedSkill) return;
    if (!selectedSkill.name.trim()) {
      setToast({ message: "Please enter a valid protocol name before saving.", variant: "error" });
      return;
    }

    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/skills`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: selectedSkill.name.toLowerCase().replace(/\s+/g, "_"),
          content: selectedSkill.content,
          metadata: selectedSkill.metadata
        })
      });
      if (!res.ok) throw new Error("Save failed");
      await fetchSkills();
      setToast({ message: "Protocol saved successfully!", variant: "success" });
    } catch (e: any) {
      setToast({ message: "Save failed: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (name: string) => {
    const isSaved = skills.includes(name);
    if (!isSaved) {
      setSelectedSkill(null);
      return;
    }

    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles`);
      if (!res.ok) throw new Error("Error loading profiles");
      const profiles = await res.json();

      const referencingProfiles = profiles.filter((p: any) =>
        p.skills?.includes(name) || p.critical_skills?.includes(name)
      ).map((p: any) => p.name);

      if (referencingProfiles.length > 0) {
        setBlockingProfiles(referencingProfiles);
        setIsBlockedModalOpen(true);
        return;
      }

      setIsDeleteModalOpen(true);
      setDeleteConfirmInput("");
    } catch (e: any) {
      setToast({ message: "Error checking profiles: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const executeDelete = async (name: string) => {
    setLoading(true);
    try {
      const res = await apiFetch(
        `${apiBase()}/admin/skills/${encodeURIComponent(name)}`,
        {
          method: "DELETE"
        }
      );
      if (!res.ok) throw new Error("Error during deletion");
      fetchSkills();
      if (selectedSkill?.name === name) setSelectedSkill(null);
      setIsDeleteModalOpen(false);
      setDeleteConfirmInput("");
      setToast({ message: "Skill successfully deleted!", variant: "success" });
    } catch (e: any) {
      setToast({ message: "Deletion failed: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async (skill: any) => {
    if (!skill || !skill.name) return;
    try {
      const res = await apiFetch(
        `${apiBase()}/admin/skills/${encodeURIComponent(skill.name)}/export`
      );
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${skill.name}.md`;
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
      const res = await apiFetch(`${apiBase()}/admin/skills/export/all`);
      if (!res.ok) throw new Error("Global export failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `all_skills.zip`;
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
    input.accept = '.md';
    input.onchange = async (e: any) => {
      const file = e.target.files[0];
      if (!file) return;

      const formData = new FormData();
      formData.append('file', file);

      setLoading(true);
      try {
        const res = await apiFetch(`${apiBase()}/admin/skills/import-preview`, {
          method: "POST",
          body: formData
        });
        if (!res.ok) throw new Error("Import failed");
        const data = await res.json();

        // Controllo duplicati
        const isDuplicate = skills.includes(data.name);

        if (isDuplicate) {
          setToast({
            message: `Warning: a skill named "${data.name}" already exists. It has been loaded into the editor; clicking SAVE will overwrite the existing file.`,
            variant: "warning"
          });
        } else {
          setToast({
            message: `Skill "${data.name}" loaded into the editor. Review and click SAVE to confirm.`,
            variant: "success"
          });
        }

        setSelectedSkill(data);
        setTagInput((data.metadata?.tags || []).join(", "));

      } catch (err: any) {
        setToast({ message: "Error during import: " + err.message, variant: "error" });
      } finally {
        setLoading(false);
      }
    };
    input.click();
  };

  return (
    <div className="min-h-screen w-full bg-[#050505] text-slate-200 font-sans flex flex-col">

      <div className="space-y-3 pb-4">
        <h2 className="text-3xl font-extrabold tracking-tight text-white font-sans">Skill Registry</h2>
        <p className="text-md text-gray-400 max-w-xl mt-2 font-sans">
          Manage agent competence and edit specialized protocol markdown files.
        </p>
      </div>

      {/* ==========================================
          HEADER: WORKSPACE CONTROLS & PROTOCOL SWITCHER
          ========================================== */}
      <header className="flex items-center justify-between px-6 py-4 bg-[#0a0a0a] border-b border-slate-800/80 sticky top-16 z-40">

        <div className="flex items-center gap-3 mr-4">
          <label className="text-xs text-slate-500 uppercase tracking-wide">Status</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as "" | "draft" | "verified")}
            className="bg-[#111] border border-slate-700 text-sm rounded px-2 py-1 text-slate-200"
          >
            <option value="">All</option>
            <option value="draft">Draft</option>
            <option value="verified">Verified</option>
          </select>
        </div>

        {/* Protocol Switcher */}
        <HeaderDropdown
          triggerIcon={<FileCode className="w-5 h-5" />}
          triggerLabelTop="Active Protocol"
          triggerLabelMain={selectedSkill ? (selectedSkill.name || "New Protocol") : "Select Protocol..."}
          items={skills.map((sName) => ({ key: sName, label: sName }))}
          selectedKey={selectedSkill?.name}
          itemIcon={<FileCode className="w-4 h-4" />}
          onItemSelect={(key) => handleEdit(key)}
          searchPlaceholder="Search protocols..."
          emptyLabel="No protocols found"
          actions={[
            {
              icon: <Wand2 className="w-4 h-4" />,
              label: "AI Wizard Generator",
              onClick: () => setIsWizardOpen(true),
              colorClass: "text-purple-400 hover:bg-purple-600/10 font-bold",
            },
            {
              icon: <Plus className="w-4 h-4" />,
              label: "New Skill",
              onClick: handleNewSkill,
              colorClass: "text-blue-400 hover:bg-blue-600/10",
            },
            {
              icon: <Upload className="w-4 h-4" />,
              label: "Import Skill",
              onClick: handleImport,
              colorClass: "text-emerald-400 hover:bg-emerald-600/10",
            },
          ]}
        />

        {/* Global Actions */}
        <div className="flex items-center gap-3">
          {selectedSkill && (
            <>
              {/* Export Current Skill */}
              <button
                onClick={() => handleExport(selectedSkill)}
                title="Export Current Skill"
                className="p-2.5 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
              >
                <Download className="w-5 h-5" />
              </button>

              {/* Delete Skill */}
              <button
                onClick={() => handleDelete(selectedSkill.name)}
                title="Delete Skill"
                className="p-2.5 rounded-lg text-slate-400 hover:bg-red-500/10 hover:text-red-500 transition-colors"
              >
                <Trash2 className="w-5 h-5" />
              </button>

              {selectedSkill.name && skillMeta[selectedSkill.name]?.status === "draft" && (
                <button
                  onClick={() => handlePromote(selectedSkill.name)}
                  disabled={loading}
                  className="flex items-center gap-2 bg-emerald-700 hover:bg-emerald-600 text-white px-4 py-2.5 rounded-lg font-bold text-sm transition-all disabled:opacity-50"
                >
                  Promote to verified
                </button>
              )}

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

          {/* Export All Skills */}
          {skills.length > 0 && (
            <button
              onClick={handleExportAll}
              title="Export All Skills"
              className="flex items-center gap-2 px-3 py-2 bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 rounded-lg font-semibold text-xs transition-all"
            >
              <Download className="w-3.5 h-3.5" /> Export All
            </button>
          )}
        </div>
      </header>

      {/* ==========================================
          MAIN EDITOR: LAYOUT ORIZZONTALE
          ========================================== */}
      {selectedSkill ? (
        <main className="flex-1 p-6 lg:p-10 overflow-y-auto">
          <div className="max-w-[1600px] mx-auto flex flex-col gap-6 lg:gap-8">

            {/* INLINE AI SKILL CO-PILOT ASSISTANT BAR */}
            <div className="rounded-2xl border border-purple-500/30 bg-gradient-to-r from-purple-950/40 via-[#121216] to-purple-950/20 p-4 space-y-3 shadow-xl backdrop-blur-md">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-purple-400 font-bold text-xs uppercase tracking-wider">
                  <Wand2 className="w-4 h-4 animate-pulse" />
                  <span>AI Skill Co-Pilot — Modifica in tempo reale la skill selezionata</span>
                </div>
                <span className="text-[11px] text-purple-300/70 italic hidden sm:inline">
                  Legge lo stato ed il contenuto attuale della skill ed aggiorna il protocollo in tempo reale
                </span>
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={inlineRefinePrompt}
                  onChange={(e) => setInlineRefinePrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleRefineSkill();
                  }}
                  placeholder="Chiedi all'IA di modificare questa skill... (es: 'Aggiungi la gestione degli errori e la validazione dei dati di input')"
                  className="flex-1 bg-black/60 border border-purple-500/30 rounded-xl px-4 py-2.5 text-sm text-white placeholder:text-gray-500 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 outline-none transition-all"
                />
                <button
                  type="button"
                  onClick={() => handleRefineSkill()}
                  disabled={refineLoading || !inlineRefinePrompt.trim()}
                  className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs shadow-lg shadow-purple-900/30 disabled:opacity-50 transition-all cursor-pointer whitespace-nowrap"
                >
                  {refineLoading ? (
                    <>
                      <Sparkles className="w-4 h-4 animate-spin" />
                      <span>Aggiornamento in corso...</span>
                    </>
                  ) : (
                    <>
                      <Wand2 className="w-4 h-4" />
                      <span>Applica con IA</span>
                    </>
                  )}
                </button>
              </div>

              {/* QUICK REFINEMENT CHIPS */}
              <div className="flex items-center gap-2 flex-wrap pt-0.5">
                <span className="text-[11px] text-gray-400 font-medium">Azione rapida:</span>
                {[
                  { label: "📝 + Validazione Input", prompt: "Aggiungi la sezione di validazione formale per i dati di input." },
                  { label: "⚠️ + Gestione Errori & Fallback", prompt: "Aggiungi istruzioni di gestione delle eccezioni e strategie di fallback." },
                  { label: "📊 + Output Formattato JSON", prompt: "Formatta la sezione di output richiedendo risposte in formato JSON strutturato." },
                  { label: "🔍 + Logging Dettagliato", prompt: "Aggiungi passaggi procedurali per la registrazione dei log e del tracciamento." },
                ].map((chip) => (
                  <button
                    key={chip.label}
                    type="button"
                    onClick={() => handleRefineSkill(chip.prompt)}
                    disabled={refineLoading}
                    className="px-2.5 py-1 rounded-lg bg-purple-900/20 border border-purple-500/25 text-purple-300 hover:bg-purple-800/40 hover:border-purple-400 text-xs transition-all cursor-pointer font-medium disabled:opacity-50"
                  >
                    {chip.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12">

              {/* COLONNA EDITOR (Full width for editor focus) */}
              <div className="lg:col-span-12 flex flex-col gap-6">

                <div className="grid grid-cols-1 gap-6">
                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-wider text-slate-500">Protocol Name</label>
                    <input
                      type="text"
                      value={selectedSkill.name}
                      placeholder="e.g. kubernetes_docs"
                      onChange={(e) => setSelectedSkill({ ...selectedSkill, name: e.target.value.toLowerCase().replace(/\s+/g, "_") })}
                      className="w-full bg-[#0a0a0a] border border-slate-800 rounded-xl px-4 py-3 text-slate-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all font-medium outline-none font-mono"
                    />
                  </div>
                </div>

                {/* Description + Tags */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

                  {/* Description */}
                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-wider text-slate-500">Description</label>
                    <textarea
                      value={selectedSkill.metadata?.description || ""}
                      placeholder="Short description of what this skill does..."
                      rows={3}
                      onChange={(e) =>
                        setSelectedSkill({
                          ...selectedSkill,
                          metadata: { ...(selectedSkill.metadata || {}), description: e.target.value },
                        })
                      }
                      className="w-full bg-[#0a0a0a] border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-300 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all outline-none resize-none custom-scrollbar"
                    />
                  </div>

                  {/* Tags */}
                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-wider text-slate-500">Tags</label>
                    <input
                      type="text"
                      value={tagInput}
                      placeholder="e.g. tag1, tag2, tag3"
                      onChange={(e) => {
                        const val = e.target.value;
                        setTagInput(val);
                        const parsedTags = val.split(",").map(t => t.trim()).filter(Boolean);
                        setSelectedSkill(prev => prev ? {
                          ...prev,
                          metadata: {
                            ...(prev.metadata || {}),
                            tags: parsedTags
                          }
                        } : prev);
                      }}
                      className="w-full bg-[#0a0a0a] border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-300 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all outline-none font-sans"
                    />
                  </div>

                </div>

                <div className="flex-1 flex flex-col space-y-2 min-h-[600px]">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center gap-2">
                      <FileCode className="w-4 h-4" /> Markdown Content
                    </label>
                  </div>
                  <div className="flex-1 bg-[#0a0a0a] border border-slate-800 rounded-xl p-5 text-[13px] text-slate-300 transition-all shadow-inner outline-none">
                    <BlockMarkdownEditor
                      value={selectedSkill.content}
                      onChange={(val) => setSelectedSkill({ ...selectedSkill, content: val })}
                      height={550}
                      placeholder="# Protocol Title\n\nDescribe the specialized agent protocol here..."
                      allowTasks={false}
                    />
                  </div>
                </div>
              </div>

            </div>
          </div>
        </main>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-center p-12 space-y-6 min-h-[450px]">
          <div className="space-y-1 mb-6">
            <h2 className="text-3xl font-extrabold tracking-tight text-white font-sans">Skill Registry</h2>
            <p className="text-md text-gray-400 max-w-xl mt-2 font-sans">
              Manage agent competence and edit specialized protocol markdown files.
            </p>
          </div>
          <div className="w-20 h-20 rounded-2xl bg-gradient-to-tr from-blue-500/10 to-indigo-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 shadow-xl shadow-blue-500/5">
            <FileCode className="w-10 h-10" />
          </div>
          <div className="space-y-2 max-w-sm">
            <h3 className="text-xl font-bold text-white">Select or Create a Protocol</h3>
            <p className="text-sm text-slate-400 leading-relaxed">
              Choose a specialized protocol markdown file from the list above to edit its instructions, or create a brand new skill.
            </p>
          </div>
          <button
            onClick={handleNewSkill}
            className="px-6 py-3 bg-white/10 hover:bg-white/15 border border-white/10 text-white font-semibold rounded-xl text-sm transition-all shadow-md cursor-pointer"
          >
            Create New Skill
          </button>
        </div>
      )}

      {isDeleteModalOpen && selectedSkill && (
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
                You are about to permanently delete the skill protocol <b className="text-white font-mono">{selectedSkill.name}</b>. This operation cannot be undone.
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-white/80 block">
                  Type the exact name (<span className="font-mono text-white font-bold">{selectedSkill.name}</span>) to confirm:
                </label>
                <input
                  type="text"
                  value={deleteConfirmInput}
                  onChange={(e) => setDeleteConfirmInput(e.target.value)}
                  placeholder={selectedSkill.name}
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
                onClick={() => executeDelete(selectedSkill.name)}
                disabled={deleteConfirmInput !== selectedSkill.name || loading}
                className="bg-red-600 hover:bg-red-500 text-white px-6 py-2.5 rounded-xl text-sm font-bold transition-all flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-red-600/20 cursor-pointer"
              >
                <Trash2 className="w-4 h-4" />
                {loading ? "Deleting..." : "Delete Skill"}
              </button>
            </div>
          </div>
        </div>
      )}

      {isBlockedModalOpen && selectedSkill && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl w-full max-w-xl overflow-hidden shadow-2xl animate-in zoom-in-95 duration-200">
            <div className="p-6 border-b border-white/10 flex justify-between items-center bg-white/5">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-amber-400" />
                Deletion Blocked
              </h2>
              <button
                onClick={() => setIsBlockedModalOpen(false)}
                className="text-gray-500 hover:text-white transition-colors"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div className="p-4 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-300 text-sm leading-relaxed">
                <p className="font-semibold mb-1 text-lg flex items-center gap-2">
                  <span className="text-white font-bold">Skill in Use</span>
                </p>
                The skill protocol <b className="text-white font-mono">{selectedSkill.name}</b> cannot be deleted because it is currently attached to the following agent profiles:
              </div>

              <div className="space-y-2 max-h-40 overflow-y-auto pr-1 custom-scrollbar">
                {blockingProfiles.map((pName) => (
                  <div key={pName} className="p-3 bg-black/40 border border-white/5 rounded-xl text-sm text-gray-200 font-semibold flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-blue-500"></span>
                    {pName}
                  </div>
                ))}
              </div>

              <p className="text-xs text-gray-400 italic pt-2">
                Please remove the skill from these profiles first before deleting it.
              </p>
            </div>

            <div className="p-6 border-t border-white/10 flex justify-end bg-black/20">
              <button
                onClick={() => setIsBlockedModalOpen(false)}
                className="bg-white/10 hover:bg-white/15 text-white px-6 py-2.5 rounded-xl text-sm font-bold transition-all cursor-pointer"
              >
                I understand
              </button>
            </div>
          </div>
        </div>
      )}

      {/* AI SKILL WIZARD MODAL */}
      {isWizardOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200">
          <div className="w-full max-w-xl rounded-2xl bg-[#121212] border border-purple-500/40 p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <div className="flex items-center gap-2 text-purple-400 font-bold text-lg">
                <Wand2 className="w-5 h-5 animate-pulse" />
                <span>AI Skill Creation Wizard</span>
              </div>
              <button
                onClick={() => setIsWizardOpen(false)}
                className="text-gray-400 hover:text-white p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-gray-400 leading-relaxed">
              Descrivi la procedura o la regola speciale che desideri trasformare in una Skill. L'IA genererà un protocollo Markdown completo con metadati YAML pronti per l'editing. Il contenuto verrà generato rigorosamente in <b className="text-white">Inglese</b>.
            </p>

            {/* QUICK SUGGESTION CHIPS FOR SKILLS */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
                💡 Suggerimenti per la skill:
              </label>
              <div className="flex flex-wrap gap-2">
                {[
                  { label: "📑 Validazione Documenti", add: " Includi regole dettagliate per la validazione di documenti ed allegati." },
                  { label: "🔄 Riconciliazione Dati", add: " Includi la procedura passo-passo per il controllo e la riconciliazione tra due fonti dati." },
                  { label: "⚡ Gestione Errori & Fallback", add: " Specifica le regole di fallback in caso di errore di esecuzione o tool vuoto." },
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
              placeholder="Es: Crea una skill per la riconciliazione delle fatture mensili con gli ordini d'acquisto Odoo..."
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
                      <span>Generazione Skill (EN)...</span>
                    </>
                  ) : (
                    <>
                      <Wand2 className="w-4 h-4" />
                      <span>Genera Skill con IA</span>
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
