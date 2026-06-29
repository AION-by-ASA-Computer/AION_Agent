"use client";

import { useState } from "react";
import { FolderPlus, X } from "lucide-react";
import { createSqlProject } from "@/lib/api/query-memory";
import { useT } from "@/lib/i18n/use-t";

type Props = {
  open: boolean;
  onClose: () => void;
  userId: string;
  token?: string | null;
  profileSlug?: string;
  onCreated: (slug: string) => void;
};

export function ProjectCreateModal({
  open,
  onClose,
  userId,
  token,
  profileSlug,
  onCreated,
}: Props) {
  const t = useT();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const onSubmit = async () => {
    const normalized = slug.trim().toLowerCase().replace(/\s+/g, "_");
    if (!normalized || !name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const p = await createSqlProject(
        userId,
        {
          slug: normalized,
          display_name: name.trim(),
          description: desc.trim() || undefined,
        },
        token,
        profileSlug
      );
      onCreated(p.slug);
      setSlug("");
      setName("");
      setDesc("");
      onClose();
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
        aria-labelledby="project-create-title"
        className="w-full max-w-md rounded-2xl border border-border/60 bg-card p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <FolderPlus size={20} aria-hidden />
            </div>
            <div>
              <h2 id="project-create-title" className="text-base font-semibold">
                {t("memory_project.new_project")}
              </h2>
              <p className="text-xs text-muted-foreground">{t("memory_project.create_modal_hint")}</p>
            </div>
          </div>
          <button type="button" className="rounded-lg p-1 text-muted-foreground hover:bg-muted" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-xs font-medium text-muted-foreground">{t("memory_project.slug_label")}</span>
            <input
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              placeholder={t("memory_project.slug_placeholder")}
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-muted-foreground">{t("memory_project.name_label")}</span>
            <input
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              placeholder={t("memory_project.name_placeholder")}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-muted-foreground">{t("memory_project.desc_label")}</span>
            <textarea
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              placeholder={t("memory_project.desc_placeholder")}
              rows={3}
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
            />
          </label>
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button type="button" className="rounded-lg border border-border px-4 py-2 text-sm" onClick={onClose}>
            {t("btn.cancel")}
          </button>
          <button
            type="button"
            disabled={busy}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            onClick={() => void onSubmit()}
          >
            {t("memory_project.create_btn")}
          </button>
        </div>
      </div>
    </div>
  );
}
