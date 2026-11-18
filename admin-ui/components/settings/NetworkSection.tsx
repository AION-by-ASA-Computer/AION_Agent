"use client";

/**
 * Settings -> Network: company certificate authority and jail network summary.
 *
 * The admin uploads the company CA (PEM or DER) so MCP servers and the agent's
 * jails trust internal applications served over HTTPS with company certificates
 * (CRM, ERP, Plane…). The backend (`/admin/network/ca`, src/api/admin_network.py)
 * validates it, stores it in the AION data volume and applies it immediately to
 * running custom MCP servers: no .env edit, no restart. When the server sets
 * `AION_SANDBOX_CA_BUNDLE` in .env, that file wins and this section is read-only.
 *
 * Self-saving section (like SMTP): every action is persisted on its own.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, FileBadge, Loader2, Trash2, TriangleAlert, Upload } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { outlineBtn } from "@/components/ui/classes";
import { Group, Mono, Note, SectionHead } from "./ui";
import { K, type SectionCtx } from "./types";

type CertInfo = {
  subject: string;
  issuer: string;
  not_before: string;
  not_after: string;
  expired: boolean;
  is_ca: boolean;
  fingerprint_sha256: string;
};

type CaState = {
  source: "upload" | "env" | null;
  env_path: string | null;
  certificates: CertInfo[];
  error?: string | null;
  filename?: string | null;
  uploaded_by?: string | null;
  uploaded_at?: string | null;
  warnings?: string[];
  network: {
    container_runtime: string;
    proxy: boolean;
  };
};

const m = `${K}.network`;

const fmtDate = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString() : "—");

/** Backend error body -> readable message. */
async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body?.detail?.message || (typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`);
  } catch {
    return `HTTP ${res.status}`;
  }
}

export function NetworkSection({ t, notify }: Pick<SectionCtx, "t" | "notify">) {
  const [state, setState] = useState<CaState | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState<"upload" | "delete" | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/network/ca`);
      if (!res.ok) throw new Error(String(res.status));
      setState((await res.json()) as CaState);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount (same as SmtpSection)
    void load();
  }, [load]);

  const upload = async (file: File) => {
    setBusy("upload");
    setWarnings([]);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await apiFetch(`${apiBase()}/admin/network/ca`, { method: "PUT", body: form });
      if (!res.ok) throw new Error(await errorMessage(res));
      const data = (await res.json()) as CaState & { servers_restarted: number };
      setState(data);
      setWarnings(data.warnings ?? []);
      notify(t(`${m}.uploaded`, { count: data.servers_restarted }), "success");
    } catch (err: unknown) {
      notify(t(`${m}.upload_error`, { error: err instanceof Error ? err.message : String(err) }), "error");
    } finally {
      setBusy(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const remove = async () => {
    setBusy("delete");
    try {
      const res = await apiFetch(`${apiBase()}/admin/network/ca`, { method: "DELETE" });
      if (!res.ok) throw new Error(await errorMessage(res));
      setWarnings([]);
      await load();
      notify(t(`${m}.removed`), "success");
    } catch (err: unknown) {
      notify(t(`${m}.upload_error`, { error: err instanceof Error ? err.message : String(err) }), "error");
    } finally {
      setBusy(null);
    }
  };

  const managedByEnv = state?.source === "env";

  return (
    <div className="flex flex-col gap-6">
      <SectionHead title={t(`${m}.title`)} description={t(`${m}.description`)} />

      {loadFailed && <Note tone="warn">{t(`${m}.load_error`)}</Note>}

      <Group
        title={t(`${m}.ca_title`)}
        description={t(`${m}.ca_description`)}
        action={
          !managedByEnv && (
            <div className="flex gap-2">
              <input
                ref={fileRef}
                type="file"
                accept=".pem,.crt,.cer,.der"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void upload(f);
                }}
              />
              <button type="button" className={outlineBtn} disabled={busy !== null} onClick={() => fileRef.current?.click()}>
                {busy === "upload" ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Upload className="h-3.5 w-3.5" aria-hidden />}
                {state?.source ? t(`${m}.replace`) : t(`${m}.upload`)}
              </button>
              {state?.source === "upload" && (
                <button type="button" className={outlineBtn} disabled={busy !== null} onClick={() => void remove()}>
                  {busy === "delete" ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Trash2 className="h-3.5 w-3.5" aria-hidden />}
                  {t(`${m}.remove`)}
                </button>
              )}
            </div>
          )
        }
      >
        <div className="flex flex-col gap-3 px-5 py-4">
          {managedByEnv && (
            <Note>
              {t(`${m}.managed_by_env`)} <Mono>{state?.env_path}</Mono>
            </Note>
          )}
          {state && !state.source && <p className="text-sm text-muted-foreground">{t(`${m}.none`)}</p>}
          {state?.error && <Note tone="warn">{state.error}</Note>}
          {state?.source === "upload" && (
            <p className="text-xs text-muted-foreground">
              {t(`${m}.uploaded_meta`, {
                file: state.filename || "—",
                user: state.uploaded_by || "—",
                date: fmtDate(state.uploaded_at),
              })}
            </p>
          )}
          {warnings.map((w) => (
            <p key={w} className="flex items-start gap-2 text-xs text-warning">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              {w}
            </p>
          ))}
          {state?.certificates.map((c) => (
            <div key={c.fingerprint_sha256} className="flex items-start gap-3 rounded-xl border border-border bg-background/60 p-3">
              <FileBadge className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <div className="min-w-0 flex-1 text-sm">
                <p className="break-all font-medium">{c.subject}</p>
                <p className="break-all text-xs text-muted-foreground">
                  {t(`${m}.issuer`)}: {c.issuer}
                </p>
                <p className={cn("mt-1 flex items-center gap-1.5 text-xs", c.expired ? "text-destructive" : "text-muted-foreground")}>
                  {c.expired ? <TriangleAlert className="h-3 w-3" aria-hidden /> : <CheckCircle2 className="h-3 w-3 text-success" aria-hidden />}
                  {c.expired ? t(`${m}.expired`, { date: fmtDate(c.not_after) }) : t(`${m}.valid_until`, { date: fmtDate(c.not_after) })}
                  {!c.is_ca && <span className="ml-1 rounded bg-secondary px-1.5 py-0.5">{t(`${m}.not_ca`)}</span>}
                </p>
                <p className="mt-1 break-all font-mono text-[10.5px] text-muted-foreground">SHA-256 {c.fingerprint_sha256}</p>
              </div>
            </div>
          ))}
        </div>
      </Group>

      {state && (
        <Group title={t(`${m}.jail_title`)} description={t(`${m}.jail_description`)}>
          <dl className="grid gap-x-6 gap-y-2 px-5 py-4 text-sm sm:grid-cols-[max-content_1fr]">
            <dt className="text-muted-foreground">{t(`${m}.engine`)}</dt>
            <dd className="font-mono">{state.network.container_runtime}</dd>
            <dt className="text-muted-foreground">{t(`${m}.proxy`)}</dt>
            <dd>{state.network.proxy ? t(`${m}.proxy_on`) : t(`${m}.proxy_off`)}</dd>
          </dl>
          <div className="px-5 pb-4">
            <Note>{t(`${m}.jail_note`)}</Note>
          </div>
        </Group>
      )}
    </div>
  );
}
