"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import type { ToastState } from "@/components/PageToast";
import { matchConnectorRow } from "@/lib/mcpConnectorUi";
import { type IntegrationPolicyRow } from "@/lib/mcpIntegrationPolicy";
import { oauthAdminSetupPending } from "@/lib/mcpOAuthSetup";
import { useT } from "@/lib/i18n/use-t";

export type Profile = {
  name: string;
  slug?: string;
  description?: string;
  instructions?: string;
  skills: string[];
  critical_skills: string[];
  mcp_servers: string[];
  native_tool_groups: string[];
};

export type ProfileSummary = Profile;

export type SkillInfo = { description: string; tags: string[] };

/** Tool bundles that run in-process rather than as MCP servers. */
export const NATIVE_TOOL_BUNDLES = ["web_research", "deep_research", "mnemos"];

const LAST_KEY = "aion_last_selected_profile";

/** Canonical profile key for API paths (backend resolves slug only). */
export function profileSlug(p: { slug?: string; name?: string }): string {
  if (p.slug) return p.slug;
  return (p.name || "").trim().toLowerCase().replace(/\s+/g, "_");
}

function normalize(data: Partial<Profile> & { name?: string }): Profile {
  return {
    ...data,
    name: data.name || "",
    skills: Array.isArray(data.skills) ? data.skills : [],
    critical_skills: Array.isArray(data.critical_skills) ? data.critical_skills : [],
    mcp_servers: Array.isArray(data.mcp_servers) ? data.mcp_servers : [],
    native_tool_groups: Array.isArray(data.native_tool_groups) ? data.native_tool_groups : [],
  };
}

function snapshot(p: Profile | null): string | null {
  return p ? JSON.stringify(normalize(p)) : null;
}

async function errorDetail(res: Response): Promise<string> {
  const err = await res.json().catch(() => ({}));
  return typeof err?.detail === "string" ? err.detail : `HTTP ${res.status}`;
}

function download(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export function useProfiles() {
  const t = useT();
  const k = "admin_profiles.toast";
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [listLoaded, setListLoaded] = useState(false);
  const [selected, setSelected] = useState<Profile | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<ToastState>(null);

  const [skills, setSkills] = useState<Record<string, SkillInfo>>({});
  const [mcpDescriptions, setMcpDescriptions] = useState<Record<string, string>>({});
  const [registryBySlug, setRegistryBySlug] = useState<
    Record<string, { type?: string; aion_connector_id?: string; description?: string }>
  >({});
  const [integrationBySlug, setIntegrationBySlug] = useState<Record<string, IntegrationPolicyRow>>({});
  const [connectorRows, setConnectorRows] = useState<Record<string, unknown>[]>([]);

  const [wizardLoading, setWizardLoading] = useState(false);
  const [refineLoading, setRefineLoading] = useState(false);

  const open = useCallback((p: Profile | null, persisted: boolean) => {
    const n = p ? normalize(p) : null;
    setSelected(n);
    setSaved(persisted ? snapshot(n) : null);
  }, []);

  const loadDetail = useCallback(
    async (slug: string): Promise<Profile> => {
      const res = await apiFetch(`${apiBase()}/admin/profiles/${encodeURIComponent(slug)}`);
      if (!res.ok) throw new Error(await errorDetail(res));
      return normalize(await res.json());
    },
    [],
  );

  const fetchProfiles = useCallback(
    async (selectFirst: boolean) => {
      try {
        const res = await apiFetch(`${apiBase()}/admin/profiles`);
        if (!res.ok) throw new Error(await errorDetail(res));
        const data: ProfileSummary[] = (await res.json()).map(normalize);
        setProfiles(data);
        if (selectFirst && data.length > 0) {
          let last: string | null = null;
          try {
            last = localStorage.getItem(LAST_KEY);
          } catch {
            // storage unavailable
          }
          const target = last && data.some((p) => profileSlug(p) === last) ? last : profileSlug(data[0]);
          open(await loadDetail(target), true);
        }
      } catch (e) {
        setToast({ message: t(`${k}.backend_error`, { error: (e as Error).message }), variant: "error" });
      } finally {
        setListLoaded(true);
      }
    },
    [loadDetail, open, t],
  );

  const fetchMetadata = useCallback(async () => {
    try {
      const [skillsRes, mcpRes, nativeRes, integrationsRes, catalogRes] = await Promise.all([
        apiFetch(`${apiBase()}/admin/skills`),
        apiFetch(`${apiBase()}/admin/registry`),
        apiFetch(`${apiBase()}/admin/native-tools`),
        apiFetch(`${apiBase()}/admin/mcp-integrations`),
        apiFetch(`${apiBase()}/admin/mcp/connector-catalog`),
      ]);
      const skillsMap: Record<string, SkillInfo> = skillsRes.ok ? await skillsRes.json() : {};
      const registry: Record<string, { description?: string; type?: string; aion_connector_id?: string }> =
        mcpRes.ok ? await mcpRes.json() : {};
      const native = nativeRes.ok ? await nativeRes.json() : null;
      const descriptions: Record<string, string> = {};
      for (const [key, cfg] of Object.entries(registry)) descriptions[key] = cfg?.description || "";
      if (native?.bundles) {
        for (const [key, bundle] of Object.entries(native.bundles)) {
          descriptions[key] = (bundle as { description?: string })?.description || "";
        }
      }
      if (integrationsRes.ok) {
        const data = await integrationsRes.json();
        const map: Record<string, IntegrationPolicyRow> = {};
        for (const row of (data.integrations || []) as IntegrationPolicyRow[]) map[row.server_slug] = row;
        setIntegrationBySlug(map);
      }
      if (catalogRes.ok) {
        const data = await catalogRes.json();
        setConnectorRows(Array.isArray(data.connectors) ? data.connectors : []);
      }
      setSkills(skillsMap);
      setMcpDescriptions(descriptions);
      setRegistryBySlug(registry);
    } catch (e) {
      console.error("Failed to fetch available metadata", e);
    }
  }, []);

  useEffect(() => {
    const id = setTimeout(() => {
      void fetchProfiles(true);
      void fetchMetadata();
    }, 0);
    return () => clearTimeout(id);
  }, [fetchProfiles, fetchMetadata]);

  const mcpAwaitingSetup = useCallback(
    (slug: string) => {
      const cfg = registryBySlug[slug];
      const policy = integrationBySlug[slug];
      const connector = matchConnectorRow(slug, cfg?.aion_connector_id || policy?.aion_connector_id || undefined, connectorRows);
      return oauthAdminSetupPending(policy?.oauth_config, connector, cfg);
    },
    [registryBySlug, integrationBySlug, connectorRows],
  );

  const select = useCallback(
    async (slug: string) => {
      setLoadingProfile(true);
      try {
        open(await loadDetail(slug), true);
        try {
          localStorage.setItem(LAST_KEY, slug);
        } catch {
          // storage unavailable
        }
      } catch (e) {
        setToast({ message: t(`${k}.load_error`, { error: (e as Error).message }), variant: "error" });
      } finally {
        setLoadingProfile(false);
      }
    },
    [loadDetail, open, t],
  );

  const update = useCallback((patch: Partial<Profile> | ((p: Profile) => Partial<Profile>)) => {
    setSelected((prev) => (prev ? { ...prev, ...(typeof patch === "function" ? patch(prev) : patch) } : prev));
  }, []);

  const createBlank = useCallback(() => {
    open(
      {
        name: "",
        description: "Custom specialized AI agent",
        instructions: "You are an expert AI assistant dedicated to assisting the user with specialized tasks.",
        skills: [],
        critical_skills: [],
        native_tool_groups: ["web_research", "mnemos"],
        mcp_servers: [],
      },
      false,
    );
  }, [open]);

  const isPersisted = useMemo(
    () => !!selected && profiles.some((p) => profileSlug(p) === profileSlug(selected)) && saved !== null,
    [profiles, selected, saved],
  );
  const dirty = useMemo(() => !!selected && snapshot(selected) !== saved, [selected, saved]);

  const save = useCallback(async () => {
    if (!selected) return;
    if (!selected.name.trim()) {
      setToast({ message: t(`${k}.name_required`), variant: "error" });
      return;
    }
    setSaving(true);
    try {
      const blocked = selected.mcp_servers.filter((s) => mcpAwaitingSetup(s));
      const payload = { ...selected, mcp_servers: selected.mcp_servers.filter((s) => !mcpAwaitingSetup(s)) };
      const res = await apiFetch(`${apiBase()}/admin/profiles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      const data = await res.json();
      const slug = data.slug || profileSlug(selected);
      try {
        localStorage.setItem(LAST_KEY, slug);
      } catch {
        // storage unavailable
      }
      setToast(
        blocked.length > 0
          ? { message: t(`${k}.saved_without_mcp`, { servers: blocked.join(", ") }), variant: "warning" }
          : { message: t(`${k}.saved`), variant: "success" },
      );
      await fetchProfiles(false);
      open(await loadDetail(slug), true);
    } catch (e) {
      setToast({ message: t(`${k}.save_error`, { error: (e as Error).message }), variant: "error" });
    } finally {
      setSaving(false);
    }
  }, [selected, mcpAwaitingSetup, fetchProfiles, loadDetail, open, t]);

  const remove = useCallback(async () => {
    if (!selected) return false;
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles/${encodeURIComponent(profileSlug(selected))}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      try {
        localStorage.removeItem(LAST_KEY);
      } catch {
        // storage unavailable
      }
      open(null, false);
      await fetchProfiles(false);
      setToast({ message: t(`${k}.deleted`), variant: "success" });
      return true;
    } catch (e) {
      setToast({ message: t(`${k}.delete_error`, { error: (e as Error).message }), variant: "error" });
      return false;
    } finally {
      setSaving(false);
    }
  }, [selected, fetchProfiles, open, t]);

  /** Drops an unsaved draft without touching the server. */
  const discardDraft = useCallback(() => open(null, false), [open]);

  const toggleSkill = useCallback(
    (skill: string) =>
      update((p) => {
        const on = p.skills.includes(skill);
        return {
          skills: on ? p.skills.filter((s) => s !== skill) : [...p.skills, skill],
          critical_skills: on ? p.critical_skills.filter((s) => s !== skill) : p.critical_skills,
        };
      }),
    [update],
  );

  const toggleCritical = useCallback(
    (skill: string) =>
      update((p) => ({
        critical_skills: p.critical_skills.includes(skill)
          ? p.critical_skills.filter((s) => s !== skill)
          : [...p.critical_skills, skill],
      })),
    [update],
  );

  const toggleMcp = useCallback(
    (mcp: string) => {
      if (!selected) return;
      if (mcpAwaitingSetup(mcp) && !selected.mcp_servers.includes(mcp)) {
        setToast({ message: t(`${k}.mcp_needs_oauth`), variant: "warning" });
        return;
      }
      update((p) => ({
        mcp_servers: p.mcp_servers.includes(mcp) ? p.mcp_servers.filter((s) => s !== mcp) : [...p.mcp_servers, mcp],
      }));
    },
    [selected, mcpAwaitingSetup, update, t],
  );

  const toggleNative = useCallback(
    (id: string) =>
      update((p) => ({
        native_tool_groups: p.native_tool_groups.includes(id)
          ? p.native_tool_groups.filter((s) => s !== id)
          : [...p.native_tool_groups, id],
      })),
    [update],
  );

  const exportOne = useCallback(async () => {
    if (!selected) return;
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles/${encodeURIComponent(profileSlug(selected))}/export`);
      if (!res.ok) throw new Error(await errorDetail(res));
      download(await res.blob(), `${selected.name.toLowerCase().replace(/\s+/g, "_")}.yaml`);
    } catch (e) {
      setToast({ message: t(`${k}.export_error`, { error: (e as Error).message }), variant: "error" });
    }
  }, [selected, t]);

  const exportAll = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles/export/all`);
      if (!res.ok) throw new Error(await errorDetail(res));
      download(await res.blob(), "all_profiles.zip");
    } catch (e) {
      setToast({ message: t(`${k}.export_error`, { error: (e as Error).message }), variant: "error" });
    }
  }, [t]);

  const importFile = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".yml,.yaml";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      const form = new FormData();
      form.append("file", file);
      try {
        const res = await apiFetch(`${apiBase()}/admin/profiles/import-preview`, { method: "POST", body: form });
        if (!res.ok) throw new Error(await errorDetail(res));
        const data = normalize(await res.json());
        const duplicate = profiles.some((p) => p.name.toLowerCase() === data.name.toLowerCase());
        setToast(
          duplicate
            ? { message: t(`${k}.import_duplicate`, { name: data.name }), variant: "warning" }
            : { message: t(`${k}.imported`), variant: "success" },
        );
        open(data, false);
      } catch (e) {
        setToast({ message: t(`${k}.import_error`, { error: (e as Error).message }), variant: "error" });
      }
    };
    input.click();
  }, [profiles, open, t]);

  const generate = useCallback(
    async (prompt: string) => {
      if (!prompt.trim()) return false;
      setWizardLoading(true);
      try {
        const res = await apiFetch(`${apiBase()}/admin/profiles/wizard-generate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt }),
        });
        if (!res.ok) throw new Error(await errorDetail(res));
        const data = await res.json();
        open(
          {
            name: data.name || "Wizard Agent",
            description: data.description || "",
            instructions: data.instructions || "",
            skills: Array.isArray(data.skills) ? data.skills : [],
            critical_skills: [],
            mcp_servers: Array.isArray(data.mcp_servers) ? data.mcp_servers : [],
            native_tool_groups: [],
          },
          false,
        );
        setToast({ message: t(`${k}.generated`, { name: data.name || "Agent" }), variant: "success" });
        return true;
      } catch (e) {
        setToast({ message: t(`${k}.generate_error`, { error: (e as Error).message }), variant: "error" });
        return false;
      } finally {
        setWizardLoading(false);
      }
    },
    [open, t],
  );

  const refine = useCallback(
    async (prompt: string) => {
      if (!prompt.trim() || !selected) return false;
      setRefineLoading(true);
      try {
        const res = await apiFetch(`${apiBase()}/admin/profiles/wizard-refine`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt, current_profile: selected }),
        });
        if (!res.ok) throw new Error(await errorDetail(res));
        const data = await res.json();
        update({
          name: data.name || selected.name,
          description: data.description || selected.description,
          instructions: data.instructions || selected.instructions,
          skills: Array.isArray(data.skills) ? data.skills : selected.skills,
          mcp_servers: Array.isArray(data.mcp_servers) ? data.mcp_servers : selected.mcp_servers,
        });
        setToast({ message: t(`${k}.refined`), variant: "success" });
        return true;
      } catch (e) {
        setToast({ message: t(`${k}.refine_error`, { error: (e as Error).message }), variant: "error" });
        return false;
      } finally {
        setRefineLoading(false);
      }
    },
    [selected, update, t],
  );

  return {
    profiles,
    listLoaded,
    selected,
    loadingProfile,
    saving,
    dirty,
    isPersisted,
    toast,
    setToast,
    skills,
    mcpDescriptions,
    mcpAwaitingSetup,
    wizardLoading,
    refineLoading,
    select,
    update,
    createBlank,
    save,
    remove,
    discardDraft,
    toggleSkill,
    toggleCritical,
    toggleMcp,
    toggleNative,
    exportOne,
    exportAll,
    importFile,
    generate,
    refine,
  };
}
