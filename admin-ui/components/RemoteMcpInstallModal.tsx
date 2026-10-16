"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, Loader2, ShieldCheck } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { Dialog } from "@/components/profiles/Dialog";
import { Select } from "@/components/ui/Select";
import { ghostBtn, inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";

export type RemoteCatalogPreset = {
  id: string;
  title?: string;
  description?: string;
  remote_url?: string;
  remote_url_template?: boolean;
  auth_type?: string;
  official_doc_url?: string;
  featured_remote?: boolean;
  featured_catalog?: boolean;
  install_type?: string;
};

type RemoteProbe = {
  type?: string;
  url?: string;
  credential_mode?: string;
  oauth_provider?: string;
  oauth_server?: string;
  oauth_token_url?: string;
  hint?: string;
  remote_error?: string;
};

type RemoteMcpInstallModalProps = {
  open: boolean;
  onClose: () => void;
  onInstalled: (serverSlug: string) => void;
  presets?: RemoteCatalogPreset[];
  initialUrl?: string;
  initialDisplayName?: string;
  initialConnectorId?: string;
  installing?: boolean;
  onInstallStart?: () => void;
  onInstallEnd?: () => void;
};

const AUTH_TYPES = ["auto", "oauth2", "api-key", "basic", "none"] as const;
const KNOWN_AUTH = ["none", "oauth2", "api-key", "basic"];
const MODES = ["none", "org_shared", "per_user"];

const labelCls = "text-sm font-medium";

async function errorDetail(res: Response): Promise<string> {
  let detail = `HTTP ${res.status}`;
  try {
    const body = await res.json();
    if (body?.detail != null) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch {
    /* body is not JSON */
  }
  return detail;
}

/** Mounted only while open, so every opening starts from the seed props with fresh state. */
export function RemoteMcpInstallModal(props: RemoteMcpInstallModalProps) {
  if (!props.open) return null;
  return <RemoteForm {...props} />;
}

function RemoteForm({
  onClose,
  onInstalled,
  presets = [],
  initialUrl = "",
  initialDisplayName = "",
  initialConnectorId = "",
  installing = false,
  onInstallStart,
  onInstallEnd,
}: RemoteMcpInstallModalProps) {
  const t = useT();
  const k = "admin_hub.remote";
  const [url, setUrl] = useState(initialUrl);
  const [displayName, setDisplayName] = useState(initialDisplayName);
  const [connectorId, setConnectorId] = useState(initialConnectorId);
  const [authType, setAuthType] = useState<string>("auto");
  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<RemoteProbe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [localInstalling, setLocalInstalling] = useState(false);

  const busy = installing || localInstalling;
  const trimmed = url.trim();
  const hasPlaceholder = trimmed.includes("{") || trimmed.includes("}");
  const featuredPresets = useMemo(() => presets.filter((p) => p.remote_url), [presets]);

  const applyPreset = (preset: RemoteCatalogPreset) => {
    if (preset.remote_url) setUrl(preset.remote_url);
    if (preset.title) setDisplayName(preset.title);
    setConnectorId(preset.id);
    setProbe(null);
    setError(null);
  };

  const validate = (): boolean => {
    if (!trimmed) {
      setError(t(`${k}.err_empty`));
      return false;
    }
    if (hasPlaceholder) {
      setError(t(`${k}.err_placeholder`));
      return false;
    }
    return true;
  };

  const handleProbe = async () => {
    if (!validate()) return;
    setProbing(true);
    setError(null);
    setProbe(null);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/probe-remote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: trimmed }),
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      const data = await res.json();
      setProbe((data.probe as RemoteProbe) || null);
      const found = data.probe?.type ? String(data.probe.type) : "";
      if (authType === "auto" && KNOWN_AUTH.includes(found)) setAuthType(found);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setProbing(false);
    }
  };

  const handleInstall = async () => {
    if (!validate()) return;
    setLocalInstalling(true);
    onInstallStart?.();
    setError(null);
    try {
      const payload: Record<string, string> = { url: trimmed };
      if (displayName.trim()) payload.display_name = displayName.trim();
      if (connectorId.trim()) payload.connector_id = connectorId.trim();
      if (authType !== "auto") payload.auth_type = authType;
      const res = await apiFetch(`${apiBase()}/admin/market/install-remote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      const data = await res.json();
      onInstalled(String(data.name || data.server_slug || ""));
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLocalInstalling(false);
      onInstallEnd?.();
    }
  };

  const probeRows: { label: string; value: string }[] = probe
    ? [
        probe.oauth_provider && { label: t(`${k}.probe_provider`), value: probe.oauth_provider },
        probe.oauth_server && { label: t(`${k}.probe_server`), value: probe.oauth_server },
        probe.oauth_token_url && { label: t(`${k}.probe_token`), value: probe.oauth_token_url },
        probe.credential_mode && {
          label: t(`${k}.probe_mode`),
          value: MODES.includes(probe.credential_mode) ? t(`admin_hub.scope.${probe.credential_mode}`) : probe.credential_mode,
        },
      ].filter((r): r is { label: string; value: string } => Boolean(r))
    : [];

  return (
    <Dialog title={t(`${k}.title`)} closeLabel={t(`${k}.cancel`)} onClose={onClose} className="max-w-2xl">
      <form
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          void handleInstall();
        }}
      >
        <p className="-mt-1 text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>

        <div className="flex max-h-[56vh] flex-col gap-5 overflow-y-auto pr-1">
          {featuredPresets.length > 0 && (
            <fieldset className="flex flex-col gap-2">
              <legend className={cn(labelCls, "mb-2")}>{t(`${k}.presets`)}</legend>
              <div className="flex flex-wrap gap-1.5">
                {featuredPresets.map((p) => {
                  const active = connectorId === p.id;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => applyPreset(p)}
                      title={p.description || p.remote_url}
                      className={cn(
                        "focus-ring rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors",
                        active
                          ? "border-foreground bg-foreground text-background"
                          : "border-border bg-card text-muted-foreground hover:border-foreground/30 hover:text-foreground",
                      )}
                    >
                      {p.title || p.id}
                      {p.remote_url_template ? <span aria-hidden> *</span> : null}
                    </button>
                  );
                })}
              </div>
              {featuredPresets.some((p) => p.remote_url_template) && (
                <p className="text-xs text-muted-foreground">{t(`${k}.template_hint`)}</p>
              )}
            </fieldset>
          )}

          <div className="flex flex-col gap-1.5">
            <label htmlFor="remote-url" className={labelCls}>
              {t(`${k}.url`)}
            </label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                id="remote-url"
                type="url"
                value={url}
                autoFocus
                onChange={(e) => {
                  setUrl(e.target.value);
                  setProbe(null);
                }}
                placeholder="https://mcp.example.com/mcp"
                aria-invalid={hasPlaceholder || undefined}
                className={cn(inputCls, "min-w-0 flex-1 font-mono", hasPlaceholder && "border-warning/60")}
              />
              <button type="button" className={cn(outlineBtn, "h-[2.625rem] justify-center")} disabled={busy || probing || !trimmed} onClick={() => void handleProbe()}>
                {probing ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <ShieldCheck className="h-3.5 w-3.5" aria-hidden />}
                {probing ? t(`${k}.probing`) : t(`${k}.probe`)}
              </button>
            </div>
            {hasPlaceholder && <p className="text-xs text-warning">{t(`${k}.err_placeholder`)}</p>}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className={labelCls}>
                {t(`${k}.name`)} <span className="font-normal text-muted-foreground">· {t(`${k}.optional`)}</span>
              </span>
              <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="my_remote_mcp" className={inputCls} />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className={labelCls}>{t(`${k}.auth`)}</span>
              <Select
                value={authType}
                onChange={setAuthType}
                options={AUTH_TYPES.map((a) => ({ value: a, label: t(`${k}.auth_${a.replace("-", "_")}`) }))}
              />
            </label>
          </div>

          <div aria-live="polite" className="flex flex-col gap-3">
            {probing && (
              <p className="flex items-center gap-2.5 rounded-2xl bg-secondary/60 px-4 py-3 text-sm text-muted-foreground" role="status">
                <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
                {t(`${k}.probing_body`)}
              </p>
            )}

            {error && (
              <p className="flex gap-2 rounded-2xl bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive" role="alert">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                <span className="break-words">{error}</span>
              </p>
            )}

            {probe && (
              <div className="flex flex-col gap-3 rounded-2xl border border-border/70 p-4">
                <p className="flex items-center gap-2 text-sm font-semibold text-success">
                  <CheckCircle2 className="h-4 w-4" aria-hidden />
                  {t(`${k}.probe_ok`, {
                    type: KNOWN_AUTH.includes(probe.type ?? "") ? t(`${k}.auth_${String(probe.type).replace("-", "_")}`) : probe.type || t(`${k}.probe_unknown`),
                  })}
                </p>
                {probeRows.length > 0 && (
                  <dl className="grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[auto_1fr]">
                    {probeRows.map((r) => (
                      <div key={r.label} className="contents">
                        <dt className="text-muted-foreground">{r.label}</dt>
                        <dd className="break-all font-mono text-[13px]">{r.value}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {probe.hint && <p className="break-all font-mono text-xs text-muted-foreground">{probe.hint}</p>}
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-border pt-4">
          <button type="button" className={ghostBtn} onClick={onClose}>
            {t(`${k}.cancel`)}
          </button>
          <button type="submit" className={solidBtn} disabled={busy || !trimmed}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Download className="h-3.5 w-3.5" aria-hidden />}
            {busy ? t(`${k}.installing`) : t(`${k}.install`)}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
