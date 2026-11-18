"use client";

import { useEffect, useId, useRef, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Loader2,
  RotateCcw,
  Plus,
  ShieldCheck,
  Trash2,
  Upload,
} from "lucide-react";
import { Dialog } from "@/components/profiles/Dialog";
import { CustomMcpGuideDialog } from "@/components/hub/CustomMcpGuideDialog";
import { ghostBtn, inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

export type CustomMcpConfig = {
  enabled: boolean;
  force_disabled: boolean;
  sandbox_available: boolean;
  container_runtime: string;
  allow_unsandboxed: boolean;
  max_upload_mb: number;
  max_files: number;
  runtimes: string[];
};

type CredentialField = {
  key: string;
  label: string;
  secret: boolean;
  required: boolean;
  description?: string;
};

type StagedManifest = {
  aion_mcp: number;
  slug: string;
  name: string;
  description: string;
  version: string;
  runtime?: string;
  entrypoint?: string;
  credentials?: {
    mode: "none" | "org_shared" | "per_user";
    fields?: CredentialField[];
  };
  env?: Record<string, string>;
};

type StagedUpload = {
  upload_id: string;
  created_at: string;
  uploaded_by: string;
  source_kind: "py" | "zip";
  original_filename: string;
  sha256: string;
  size: number;
  files: { path: string; size: number }[];
  manifest: StagedManifest | null;
  manifest_source: "package" | "form" | null;
  entrypoint: string | null;
  suggested_slug: string;
  status: "invalid" | "needs_manifest" | "verifying" | "verify_failed" | "ready";
  errors: string[];
  warnings: string[];
  env_used: string[];
  env_check: { undeclared?: string[]; unused?: string[] };
  requirements: string[];
  /** Verification inside the jail: dependency build + probe (src/mcp_custom/verify.py). */
  build: {
    status?: "pending" | "running" | "ok" | "failed";
    step?: "dependencies" | "probe" | null;
    isolated?: boolean;
    error?: string | null;
    log?: string;
    tools?: { name: string; description: string }[];
    deps_key?: string | null;
    duration_s?: number;
  };
  review_notes: { line?: number; kind: string; message: string }[];
  readme: string | null;
  update_of: { slug: string; current_version: string; same_version: boolean } | null;
};

type Props = {
  open: boolean;
  onClose: () => void;
  /**
   * Called after a successful activation with the server slug and its registry entry
   * (``config`` from ``POST /activate``). The Hub opens the standard configuration
   * dialog with it, never the zero-install wizard: that wizard re-installs servers as
   * npx/uvx packages and would overwrite the custom entry.
   */
  onInstalled: (slug: string, config: Record<string, unknown>) => void;
  config: CustomMcpConfig | null;
};

const labelCls = "text-sm font-medium";

export function CustomMcpUploadModal({ open, onClose, onInstalled, config }: Props) {
  if (!open) return null;
  return <CustomMcpUploadForm onClose={onClose} onInstalled={onInstalled} config={config} />;
}

function CustomMcpUploadForm({ onClose, onInstalled, config }: Omit<Props, "open">) {
  const t = useT();
  const k = "admin_hub.custom_upload";
  const fileInputRef = useRef<HTMLInputElement>(null);
  const fileInputId = useId();

  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [activating, setActivating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [staged, setStaged] = useState<StagedUpload | null>(null);
  const [replaceSameVersion, setReplaceSameVersion] = useState(false);

  // Form fields when manifest is missing (needs_manifest)
  const [formSlug, setFormSlug] = useState("");
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formVersion, setFormVersion] = useState("1.0.0");
  const [formCredMode, setFormCredMode] = useState<"none" | "org_shared" | "per_user">("none");
  const [formFields, setFormFields] = useState<CredentialField[]>([]);
  const [savingManifest, setSavingManifest] = useState(false);

  const maxMb = config?.max_upload_mb ?? 20;
  // Developer guide (how to prepare server.py + aion-mcp.yaml). Shown instead of this
  // dialog while open, so the two modals are never stacked.
  const [guideOpen, setGuideOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);

  // While the package is verified in the jail (dependency build + probe, up to a few
  // minutes) poll the upload state; the backend updates it as each step finishes.
  const verifying = staged?.status === "verifying";
  const stagedId = staged?.upload_id;
  useEffect(() => {
    if (!verifying || !stagedId) return;
    const timer = setInterval(async () => {
      try {
        const res = await apiFetch(`${apiBase()}/admin/mcp-custom/uploads/${stagedId}`);
        if (res.ok) setStaged((await res.json()) as StagedUpload);
      } catch {
        /* transient error: the next tick retries */
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [verifying, stagedId]);

  /** Run the verification again after a failure (e.g. a package index was unreachable). */
  const handleRetryVerify = async () => {
    if (!staged) return;
    setRetrying(true);
    setError(null);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp-custom/uploads/${staged.upload_id}/verify`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStaged((await res.json()) as StagedUpload);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRetrying(false);
    }
  };

  const handleFile = async (file: File) => {
    if (!file) return;
    if (file.size > maxMb * 1024 * 1024) {
      setError(`Il file supera il limite massimo di ${maxMb} MB.`);
      return;
    }
    setError(null);
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await apiFetch(`${apiBase()}/admin/mcp-custom/uploads`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          if (body?.detail?.message) msg = body.detail.message;
          else if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
        } catch {
          // non-JSON response
        }
        throw new Error(msg);
      }
      const data: StagedUpload = await res.json();
      setStaged(data);
      if (data.status === "needs_manifest") {
        setFormSlug(data.suggested_slug || "");
        setFormName(data.suggested_slug ? data.suggested_slug.replace(/_/g, " ").toUpperCase() : "");
        setFormDesc("Server MCP personalizzato caricato internamente");
        setFormVersion("1.0.0");
        setFormCredMode("none");
        setFormFields([]);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  };

  const handleSaveManifest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!staged) return;
    setSavingManifest(true);
    setError(null);
    try {
      const payload = {
        aion_mcp: 1,
        slug: formSlug.trim(),
        name: formName.trim(),
        description: formDesc.trim(),
        version: formVersion.trim(),
        runtime: "python",
        entrypoint: staged.entrypoint || "server.py",
        credentials: {
          mode: formCredMode,
          fields: formCredMode !== "none" ? formFields : [],
        },
      };
      const res = await apiFetch(`${apiBase()}/admin/mcp-custom/uploads/${staged.upload_id}/manifest`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          if (body?.detail?.errors) msg = body.detail.errors.join(", ");
          else if (body?.detail?.message) msg = body.detail.message;
        } catch {
          // non-JSON
        }
        throw new Error(msg);
      }
      const updated: StagedUpload = await res.json();
      setStaged(updated);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingManifest(false);
    }
  };

  const handleActivate = async () => {
    if (!staged) return;
    setActivating(true);
    setError(null);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp-custom/uploads/${staged.upload_id}/activate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ replace_same_version: replaceSameVersion }),
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          if (body?.detail?.message) msg = body.detail.message;
          else if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
        } catch {
          // non-JSON
        }
        throw new Error(msg);
      }
      const data = await res.json();
      onInstalled(data.server_slug, (data.config || {}) as Record<string, unknown>);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActivating(false);
    }
  };

  const handleDiscard = async () => {
    if (staged) {
      try {
        await apiFetch(`${apiBase()}/admin/mcp-custom/uploads/${staged.upload_id}`, { method: "DELETE" });
      } catch {
        // silent cleanup
      }
    }
    setStaged(null);
    setError(null);
  };

  const addCredField = () => {
    setFormFields((prev) => [
      ...prev,
      {
        key: "",
        label: "",
        secret: true,
        required: true,
      },
    ]);
  };

  const removeCredField = (index: number) => {
    setFormFields((prev) => prev.filter((_, i) => i !== index));
  };

  const updateCredField = (index: number, patch: Partial<CredentialField>) => {
    setFormFields((prev) => prev.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  };

  if (guideOpen) return <CustomMcpGuideDialog onClose={() => setGuideOpen(false)} />;

  return (
    <Dialog
      title={staged ? t(`${k}.review_title`) : t(`${k}.title`)}
      closeLabel="Chiudi"
      onClose={() => {
        if (staged) void handleDiscard();
        onClose();
      }}
      className="max-w-2xl"
    >
      <div className="flex flex-col gap-5 pt-1">
        {error && (
          <div className="flex items-start gap-2.5 rounded-2xl border border-destructive/30 bg-destructive/10 p-3.5 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <div className="flex-1 whitespace-pre-line">{error}</div>
          </div>
        )}

        {!staged ? (
          <>
            <p className="-mt-1 text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>

            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                const file = e.dataTransfer.files?.[0];
                if (file) void handleFile(file);
              }}
              onClick={() => fileInputRef.current?.click()}
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed p-10 text-center transition-colors",
                dragOver ? "border-foreground bg-secondary/50" : "border-border hover:border-foreground/30 hover:bg-secondary/20",
                uploading && "pointer-events-none opacity-50",
              )}
            >
              <input
                id={fileInputId}
                ref={fileInputRef}
                type="file"
                accept=".zip,.py"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleFile(file);
                }}
              />
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-secondary text-foreground">
                {uploading ? <Loader2 className="h-6 w-6 animate-spin" /> : <Upload className="h-6 w-6" />}
              </div>
              <p className="mt-4 text-sm font-semibold">{uploading ? "Analisi pacchetto in corso…" : t(`${k}.drop_prompt`)}</p>
              <p className="mt-1 text-xs text-muted-foreground">{t(`${k}.drop_hint`, { maxMb })}</p>
            </div>

            <div className="flex items-center justify-between border-t border-border pt-4">
              <button type="button" className={cn(outlineBtn, "text-xs")} onClick={() => setGuideOpen(true)}>
                <BookOpen className="h-3.5 w-3.5" aria-hidden />
                {t(`${k}.guide_btn`)}
              </button>
              <button type="button" className={ghostBtn} onClick={onClose}>
                {t(`${k}.discard_btn`)}
              </button>
            </div>
          </>
        ) : (
          <div className="flex max-h-[68vh] flex-col gap-4 overflow-y-auto pr-1">
            {/* Status Header */}
            <div
              className={cn(
                "flex items-center gap-2.5 rounded-2xl border p-3.5 text-xs font-medium",
                staged.status === "ready" && "border-success/30 bg-success/10 text-success",
                (staged.status === "needs_manifest" || staged.status === "verifying") && "border-warning/30 bg-warning/10 text-warning",
                (staged.status === "invalid" || staged.status === "verify_failed") && "border-destructive/30 bg-destructive/10 text-destructive",
              )}
            >
              {staged.status === "ready" ? (
                <CheckCircle2 className="h-4 w-4 shrink-0" />
              ) : staged.status === "verifying" ? (
                <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
              ) : staged.status === "needs_manifest" ? (
                <AlertTriangle className="h-4 w-4 shrink-0" />
              ) : (
                <AlertCircle className="h-4 w-4 shrink-0" />
              )}
              <div className="flex-1">{t(`${k}.status_${staged.status}`)}</div>
              <span className="font-mono uppercase">{staged.source_kind}</span>
            </div>

            {/* Blocking errors if invalid */}
            {staged.errors.length > 0 && (
              <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-3 text-xs">
                <p className="font-semibold text-destructive">Errori che impediscono l&apos;installazione:</p>
                <ul className="mt-1 list-inside list-disc space-y-0.5 text-destructive/90">
                  {staged.errors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Manifest info or Form */}
            {staged.status === "needs_manifest" ? (
              <form onSubmit={handleSaveManifest} className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Configura i dettagli del server</p>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="flex flex-col gap-1">
                    <label className={labelCls}>{t(`${k}.slug`)}</label>
                    <input
                      type="text"
                      value={formSlug}
                      onChange={(e) => setFormSlug(e.target.value.toLowerCase())}
                      placeholder="es. crm_interno"
                      required
                      pattern="^[a-z][a-z0-9_]{2,40}$"
                      className={cn(inputCls, "font-mono text-xs")}
                    />
                    <p className="text-[11px] text-muted-foreground">{t(`${k}.slug_hint`)}</p>
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className={labelCls}>{t(`${k}.name`)}</label>
                    <input
                      type="text"
                      value={formName}
                      onChange={(e) => setFormName(e.target.value)}
                      placeholder="CRM Interno"
                      required
                      className={cn(inputCls, "text-xs")}
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-1">
                  <label className={labelCls}>{t(`${k}.description`)}</label>
                  <input
                    type="text"
                    value={formDesc}
                    onChange={(e) => setFormDesc(e.target.value)}
                    placeholder="Descrizione del server MCP"
                    required
                    className={cn(inputCls, "text-xs")}
                  />
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="flex flex-col gap-1">
                    <label className={labelCls}>{t(`${k}.version`)}</label>
                    <input
                      type="text"
                      value={formVersion}
                      onChange={(e) => setFormVersion(e.target.value)}
                      required
                      placeholder="1.0.0"
                      className={cn(inputCls, "font-mono text-xs")}
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className={labelCls}>{t(`${k}.cred_mode`)}</label>
                    <select
                      value={formCredMode}
                      onChange={(e) => setFormCredMode(e.target.value as "none" | "org_shared" | "per_user")}
                      className={cn(inputCls, "text-xs")}
                    >
                      <option value="none">{t(`${k}.cred_none`)}</option>
                      <option value="org_shared">{t(`${k}.cred_org_shared`)}</option>
                      <option value="per_user">{t(`${k}.cred_per_user`)}</option>
                    </select>
                  </div>
                </div>

                {formCredMode !== "none" && (
                  <div className="mt-2 flex flex-col gap-2 border-t border-border pt-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold">{t(`${k}.cred_fields`)}</span>
                      <button type="button" onClick={addCredField} className={cn(outlineBtn, "h-7 text-xs")}>
                        <Plus className="h-3 w-3" /> {t(`${k}.add_cred_field`)}
                      </button>
                    </div>
                    {formFields.map((f, idx) => (
                      <div key={idx} className="flex items-center gap-2 rounded-xl border border-border bg-secondary/20 p-2 text-xs">
                        <input
                          type="text"
                          placeholder={t(`${k}.field_key`)}
                          value={f.key}
                          onChange={(e) => updateCredField(idx, { key: e.target.value.toUpperCase() })}
                          className={cn(inputCls, "h-7 flex-1 font-mono text-xs uppercase")}
                        />
                        <input
                          type="text"
                          placeholder={t(`${k}.field_label`)}
                          value={f.label}
                          onChange={(e) => updateCredField(idx, { label: e.target.value })}
                          className={cn(inputCls, "h-7 flex-1 text-xs")}
                        />
                        <button type="button" onClick={() => removeCredField(idx)} className="text-muted-foreground hover:text-destructive">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                <div className="mt-2 flex justify-end">
                  <button type="submit" disabled={savingManifest} className={cn(solidBtn, "text-xs")}>
                    {savingManifest ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                    {t(`${k}.save_manifest`)}
                  </button>
                </div>
              </form>
            ) : staged.manifest ? (
              <div className="flex flex-col gap-2 rounded-2xl border border-border bg-card p-3.5 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2">
                  <span className="font-semibold text-foreground">{staged.manifest.name}</span>
                  <span className="rounded-full bg-secondary px-2.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                    slug: {staged.manifest.slug} • v{staged.manifest.version}
                  </span>
                </div>
                <p className="text-muted-foreground">{staged.manifest.description}</p>
                <div className="mt-1 flex flex-wrap gap-4 text-[11px] text-muted-foreground">
                  <span>
                    Credenziali: <strong className="text-foreground">{staged.manifest.credentials?.mode || "none"}</strong>
                  </span>
                  <span>
                    Entrypoint: <code className="text-foreground">{staged.entrypoint || "server.py"}</code>
                  </span>
                  <span>
                    Runtime: <strong className="text-foreground">{staged.manifest.runtime || "python"}</strong>
                  </span>
                </div>
              </div>
            ) : null}

            {/* Warnings and Notes */}
            {staged.warnings.length > 0 && (
              <div className="rounded-2xl border border-warning/20 bg-warning/5 p-3 text-xs text-warning">
                <p className="font-semibold">Avvisi:</p>
                <ul className="mt-0.5 list-inside list-disc space-y-0.5">
                  {staged.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Verification in the jail: dependencies + probe */}
            {(staged.status === "verifying" || staged.status === "verify_failed" || staged.status === "ready") && (
              <div className="flex flex-col gap-2 rounded-2xl border border-border bg-card p-3.5 text-xs">
                <p className="font-semibold">{t(`${k}.verify_title`)}</p>
                {staged.requirements.length > 0 ? (
                  <p className="text-muted-foreground">
                    {t(`${k}.verify_deps`, { count: staged.requirements.length })}{" "}
                    <span className="font-mono text-[11px] text-foreground">{staged.requirements.join(", ")}</span>
                  </p>
                ) : (
                  <p className="text-muted-foreground">{t(`${k}.verify_no_deps`)}</p>
                )}
                {staged.status === "verifying" && (
                  <p className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    {staged.build?.step === "probe" ? t(`${k}.verify_step_probe`) : t(`${k}.verify_step_deps`)}
                  </p>
                )}
                {staged.status === "ready" && (staged.build?.tools?.length ?? 0) > 0 && (
                  <div className="flex flex-col gap-1">
                    <p className="text-success">{t(`${k}.verify_tools`, { count: staged.build.tools?.length ?? 0 })}</p>
                    <ul className="flex flex-col gap-1">
                      {(staged.build.tools ?? []).map((tool) => (
                        <li key={tool.name} className="rounded-lg bg-secondary/40 px-2.5 py-1.5">
                          <code className="font-mono text-[11px] font-semibold">{tool.name}</code>
                          {tool.description && <span className="text-muted-foreground"> — {tool.description}</span>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {staged.status === "verify_failed" && (
                  <div className="flex flex-col gap-2">
                    <p className="text-destructive">{staged.build?.error}</p>
                    <button
                      type="button"
                      onClick={() => void handleRetryVerify()}
                      disabled={retrying}
                      className={cn(outlineBtn, "h-7 w-fit text-xs")}
                    >
                      {retrying ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <RotateCcw className="h-3.5 w-3.5" aria-hidden />}
                      {t(`${k}.verify_retry`)}
                    </button>
                  </div>
                )}
                {staged.build?.log && (
                  <details className="text-muted-foreground">
                    <summary className="cursor-pointer select-none">{t(`${k}.verify_log`)}</summary>
                    <pre className="mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-background p-2 font-mono text-[10.5px] leading-relaxed">
                      {staged.build.log}
                    </pre>
                  </details>
                )}
              </div>
            )}

            {/* Security Isolation Notice */}
            <div
              className={cn(
                "flex items-start gap-2.5 rounded-2xl border p-3 text-xs",
                config?.sandbox_available
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                  : "border-warning/30 bg-warning/10 text-warning",
              )}
            >
              {config?.sandbox_available ? (
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
              ) : (
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              )}
              <div className="flex-1">
                {config?.sandbox_available
                  ? t(`${k}.jail_notice`, { runtime: config.container_runtime || "container" })
                  : t(`${k}.unsandboxed_warning`)}
              </div>
            </div>

            {/* Files list */}
            {staged.files.length > 0 && (
              <div className="flex flex-col gap-1 text-xs">
                <span className="font-medium text-muted-foreground">{t(`${k}.files_in_package`, { count: staged.files.length })}</span>
                <div className="max-h-28 overflow-y-auto rounded-xl border border-border bg-secondary/20 p-2 font-mono text-[11px]">
                  {staged.files.map((f, i) => (
                    <div key={i} className="flex justify-between py-0.5">
                      <span className="truncate">{f.path}</span>
                      <span className="text-muted-foreground">{(f.size / 1024).toFixed(1)} KB</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Same version overwrite check if updating */}
            {staged.update_of?.same_version && (
              <label className="flex items-center gap-2 rounded-xl border border-warning/30 bg-warning/10 p-3 text-xs text-warning">
                <input
                  type="checkbox"
                  checked={replaceSameVersion}
                  onChange={(e) => setReplaceSameVersion(e.target.checked)}
                  className="rounded border-border text-foreground"
                />
                <span>{t(`${k}.same_version_confirm`, { version: staged.manifest?.version || "" })}</span>
              </label>
            )}

            {/* Action buttons */}
            <div className="mt-2 flex items-center justify-between border-t border-border pt-3">
              <button type="button" onClick={handleDiscard} className={ghostBtn}>
                {t(`${k}.discard_btn`)}
              </button>
              {staged.status === "ready" && (
                <button
                  type="button"
                  onClick={handleActivate}
                  disabled={activating || (staged.update_of?.same_version && !replaceSameVersion)}
                  className={cn(solidBtn, "text-xs")}
                >
                  {activating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                  {activating ? t(`${k}.activating`) : t(`${k}.activate_btn`)}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </Dialog>
  );
}

