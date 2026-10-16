"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import type { ToastState } from "@/components/PageToast";
import { useT } from "@/lib/i18n/use-t";

export type SkillSummary = {
  description?: string;
  tags?: string[];
  status?: string;
  source?: string;
  view_count?: number;
};

/** The skill open in the editor. `tags` is raw text so commas can be typed freely. */
export type SkillDraft = {
  name: string;
  description: string;
  tags: string;
  content: string;
  /** Frontmatter the editor doesn't expose — sent back untouched. */
  extra: Record<string, unknown>;
};

export const skillSlug = (name: string) => name.trim().toLowerCase().replace(/\s+/g, "_");

const parseTags = (text: string) => text.split(",").map((x) => x.trim()).filter(Boolean);

function fromApi(data: { name?: string; content?: string; description?: string; tags?: unknown; status?: string; metadata?: Record<string, unknown> }): SkillDraft {
  const meta = data.metadata ?? {};
  const tags = Array.isArray(data.tags) ? data.tags : Array.isArray(meta.tags) ? (meta.tags as string[]) : [];
  return {
    name: data.name || "",
    description: String(data.description ?? meta.description ?? ""),
    tags: tags.join(", "),
    content: data.content || "",
    extra: {},
  };
}

const snapshot = (d: SkillDraft | null) => (d ? JSON.stringify(d) : null);

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

export function useSkills() {
  const t = useT();
  const k = "admin_skills.toast";
  const [skills, setSkills] = useState<Record<string, SkillSummary>>({});
  const [listLoaded, setListLoaded] = useState(false);
  const [selected, setSelected] = useState<SkillDraft | null>(null);
  /** Name of the stored skill being edited; null while the open skill is a new draft. */
  const [persistedName, setPersistedName] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [loadingSkill, setLoadingSkill] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<ToastState>(null);
  const [wizardLoading, setWizardLoading] = useState(false);
  const [refineLoading, setRefineLoading] = useState(false);
  /** Set once the admin opens, creates or discards a skill, so the first-load default never overrides them. */
  const touched = useRef(false);

  const fail = useCallback((key: string, e: unknown) => {
    setToast({ message: t(`${k}.${key}`, { error: e instanceof Error ? e.message : String(e) }), variant: "error" });
  }, [t]);

  const refresh = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/skills?status=verified`);
      if (!res.ok) throw new Error(await errorDetail(res));
      setSkills(await res.json());
      setListLoaded(true);
    } catch (e) {
      setListLoaded(true);
      fail("backend_error", e);
    }
  }, [fail]);

  const load = (draft: SkillDraft, persisted: string | null, asSaved: boolean) => {
    touched.current = true;
    setSelected(draft);
    setPersistedName(persisted);
    setSaved(asSaved ? snapshot(draft) : null);
  };

  useEffect(() => {
    let live = true;
    apiFetch(`${apiBase()}/admin/skills?status=verified`)
      .then(async (res) => {
        if (!res.ok) throw new Error(await errorDetail(res));
        const data: Record<string, SkillSummary> = await res.json();
        if (!live) return;
        setSkills(data);
        // Open the first skill straight away.
        const first = Object.keys(data).sort((a, b) => a.localeCompare(b))[0];
        if (!first) return;
        const detail = await apiFetch(`${apiBase()}/admin/skills/${encodeURIComponent(first)}`);
        if (!detail.ok) return;
        const draft = fromApi(await detail.json());
        if (live && !touched.current) load(draft, draft.name, true);
      })
      .catch((e) => live && fail("backend_error", e))
      .finally(() => live && setListLoaded(true));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const names = useMemo(() => Object.keys(skills).sort((a, b) => a.localeCompare(b)), [skills]);
  const isPersisted = persistedName !== null;
  const dirty = !!selected && snapshot(selected) !== saved;

  const select = useCallback(async (name: string) => {
    setLoadingSkill(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/skills/${encodeURIComponent(name)}`);
      if (!res.ok) throw new Error(await errorDetail(res));
      const draft = fromApi(await res.json());
      load(draft, draft.name, true);
    } catch (e) {
      fail("load_error", e);
    } finally {
      setLoadingSkill(false);
    }
  }, [fail]);

  const createBlank = () =>
    load({ name: "", description: "", tags: "", content: t("admin_skills.editor.template"), extra: {} }, null, false);

  const discardDraft = () => {
    touched.current = true;
    setSelected(null);
    setPersistedName(null);
    setSaved(null);
  };

  const update = (patch: Partial<SkillDraft>) => setSelected((s) => (s ? { ...s, ...patch } : s));

  const save = useCallback(async () => {
    if (!selected) return false;
    const name = skillSlug(selected.name);
    if (!name) {
      setToast({ message: t(`${k}.name_required`), variant: "error" });
      return false;
    }
    setBusy(true);
    let renamedIn: string[] | null = null;
    try {
      if (persistedName && persistedName !== name) {
        const rn = await apiFetch(`${apiBase()}/admin/skills/${encodeURIComponent(persistedName)}/rename`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ new_name: name }),
        });
        if (!rn.ok) throw new Error(await errorDetail(rn));
        renamedIn = ((await rn.json()).profiles as string[]) ?? [];
        setPersistedName(name);
      }
      const res = await apiFetch(`${apiBase()}/admin/skills`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          content: selected.content,
          metadata: { ...selected.extra, description: selected.description, tags: parseTags(selected.tags) },
        }),
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      const next = { ...selected, name };
      load(next, name, true);
      await refresh();
      setToast({
        message: renamedIn?.length
          ? t(`${k}.renamed`, { name, profiles: renamedIn.join(", ") })
          : t(`${k}.saved`),
        variant: "success",
      });
      return true;
    } catch (e) {
      fail("save_error", e);
      return false;
    } finally {
      setBusy(false);
    }
  }, [selected, persistedName, refresh, fail, t]);

  /** Names of the profiles that still attach this skill (deleting it would break them). */
  const profilesUsing = async (name: string): Promise<string[] | null> => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles`);
      if (!res.ok) throw new Error(await errorDetail(res));
      const profiles: { name: string; skills?: string[]; critical_skills?: string[] }[] = await res.json();
      return profiles.filter((p) => p.skills?.includes(name) || p.critical_skills?.includes(name)).map((p) => p.name);
    } catch (e) {
      fail("check_error", e);
      return null;
    }
  };

  const remove = async () => {
    if (!persistedName) return false;
    setBusy(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/skills/${encodeURIComponent(persistedName)}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await errorDetail(res));
      discardDraft();
      await refresh();
      setToast({ message: t(`${k}.deleted`), variant: "success" });
      return true;
    } catch (e) {
      fail("delete_error", e);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const exportOne = async () => {
    if (!persistedName) return;
    try {
      const res = await apiFetch(`${apiBase()}/admin/skills/${encodeURIComponent(persistedName)}/export`);
      if (!res.ok) throw new Error(await errorDetail(res));
      download(await res.blob(), `${persistedName}.md`);
    } catch (e) {
      fail("export_error", e);
    }
  };

  const exportAll = async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/skills/export/all`);
      if (!res.ok) throw new Error(await errorDetail(res));
      download(await res.blob(), "all_skills.zip");
    } catch (e) {
      fail("export_error", e);
    }
  };

  /** Opens a file picker; `onLoaded` runs once the file is parsed into the editor. */
  const importFile = (onLoaded?: () => void) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".md";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      const form = new FormData();
      form.append("file", file);
      setBusy(true);
      try {
        const res = await apiFetch(`${apiBase()}/admin/skills/import-preview`, { method: "POST", body: form });
        if (!res.ok) throw new Error(await errorDetail(res));
        const draft = fromApi(await res.json());
        load(draft, null, false);
        onLoaded?.();
        const duplicate = !!skills[skillSlug(draft.name)];
        setToast(
          duplicate
            ? { message: t(`${k}.import_duplicate`, { name: draft.name }), variant: "warning" }
            : { message: t(`${k}.imported`), variant: "success" },
        );
      } catch (e) {
        fail("import_error", e);
      } finally {
        setBusy(false);
      }
    };
    input.click();
  };

  const generate = async (prompt: string) => {
    if (!prompt.trim()) return false;
    setWizardLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/skills/wizard-generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      const data = await res.json();
      const draft = fromApi({ ...data, name: data.name || "custom_skill" });
      load(draft, null, false);
      setToast({ message: t(`${k}.generated`, { name: draft.name }), variant: "success" });
      return true;
    } catch (e) {
      fail("generate_error", e);
      return false;
    } finally {
      setWizardLoading(false);
    }
  };

  const refine = async (prompt: string) => {
    if (!selected || !prompt.trim()) return false;
    setRefineLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/skills/wizard-refine`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          current_skill: {
            name: selected.name,
            content: selected.content,
            metadata: { ...selected.extra, description: selected.description, tags: parseTags(selected.tags) },
          },
        }),
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      const data = await res.json();
      const next = fromApi({
        name: persistedName ?? (data.name || selected.name),
        content: data.content || selected.content,
        description: data.description || selected.description,
        tags: Array.isArray(data.tags) ? data.tags : parseTags(selected.tags),
      });
      setSelected(next);
      setToast({ message: t(`${k}.refined`), variant: "success" });
      return true;
    } catch (e) {
      fail("refine_error", e);
      return false;
    } finally {
      setRefineLoading(false);
    }
  };

  return {
    skills, names, listLoaded, selected, isPersisted, persistedName, dirty, loadingSkill, busy,
    toast, setToast, wizardLoading, refineLoading,
    select, createBlank, discardDraft, update, save, remove, profilesUsing,
    exportOne, exportAll, importFile, generate, refine,
  };
}
