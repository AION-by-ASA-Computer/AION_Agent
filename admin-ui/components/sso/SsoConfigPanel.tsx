"use client";

import { useEffect, useRef, useState } from "react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { Shield, Copy, Check, AlertTriangle, Loader2, Info, Save } from "lucide-react";
import { cn } from "@/lib/cn";
import { inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";

/** Il provider accetta l'attivazione solo se la verifica ha meno di 30 minuti. */
const VALIDATION_TTL_MS = 30 * 60 * 1000;

function validatedAtMs(v: string | null): number {
  if (!v) return 0;
  // Il backend puo' mandare timestamp UTC senza fuso: senza "Z" verrebbero letti come ora locale.
  const ms = Date.parse(/(Z|[+-]\d\d:?\d\d)$/.test(v) ? v : `${v}Z`);
  return Number.isFinite(ms) ? ms : 0;
}

export function SsoConfigPanel({
  forcedProvider,
  onActivate,
  onValidatedChange,
  isActive,
}: {
  forcedProvider: "microsoft" | "google";
  /** Click esplicito su "Imposta come Predefinito" (la validazione NON attiva da sola il provider). */
  onActivate?: () => void;
  /** Notifica ogni cambio dello stato di validazione (usato dal first-setup). */
  onValidatedChange?: (validated: boolean) => void;
  isActive?: boolean;
}) {
  const [loading, setLoading] = useState(true);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [directoryId, setDirectoryId] = useState("");
  const [allowedDomains, setAllowedDomains] = useState("");

  const [validatedAt, setValidatedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [redirectUri, setRedirectUri] = useState<string>("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    fetchProviders();
    void fetchRedirectUri();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [forcedProvider]);

  // "Validata" vale solo per 30 minuti: allo scadere il banner sparisce da solo.
  const [now, setNow] = useState(() => Date.now());
  const expiresAt = validatedAtMs(validatedAt) + VALIDATION_TTL_MS;
  const fresh = !!validatedAt && expiresAt > now;
  useEffect(() => {
    if (!validatedAt) return;
    setNow(Date.now());
    const wait = expiresAt - Date.now();
    if (wait <= 0) return;
    const id = setTimeout(() => setNow(Date.now()), wait + 250);
    return () => clearTimeout(id);
  }, [validatedAt, expiresAt]);

  useEffect(() => {
    onValidatedChange?.(fresh);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fresh]);

  // Il redirect URI da registrare sull'IdP e' quello che il BACKEND usa davvero
  // (dietro Caddy e' sotto /api, in dev e' su un'altra porta): non va dedotto da window.location.
  async function fetchRedirectUri() {
    try {
      const res = await apiFetch(`${apiBase()}/admin/sso/providers/redirect-uri`);
      if (res.ok) setRedirectUri((await res.json()).redirect_uri || "");
    } catch (e) {
      console.error(e);
    }
  }

  async function fetchProviders() {
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/sso/providers`);
      if (res.ok) {
        const data = await res.json();
        const active = data.find((d: any) => d.provider === forcedProvider);
        if (active) {
          setClientId(active.client_id || "");
          setDirectoryId(active.directory_tenant_id || "");
          setAllowedDomains((active.allowed_domains || []).join(", "));
          setValidatedAt(active.validated_at);
        } else {
          setClientId("");
          setDirectoryId("");
          setAllowedDomains("");
          setValidatedAt(null);
        }
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  const handleCopy = () => {
    if (!redirectUri) return;
    navigator.clipboard.writeText(redirectUri);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSaveAndVerify = async () => {
    setError(null);
    setSaving(true);
    try {
      const domainsList = allowedDomains.split(",").map(d => d.trim()).filter(d => d);
      const res = await apiFetch(`${apiBase()}/admin/sso/providers/${forcedProvider}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          client_secret: clientSecret || undefined,
          directory_tenant_id: forcedProvider === "microsoft" ? directoryId : undefined,
          allowed_domains: domainsList.length > 0 ? domainsList : undefined,
          auto_provision: true,
          default_roles: ["user"],
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Errore nel salvataggio della configurazione SSO.");
      }

      // Baseline: se validated_at non cambia (es. salvataggio senza modifiche
      // critiche) il valore "vecchio" NON deve contare come nuova validazione.
      const baseRes = await apiFetch(`${apiBase()}/admin/sso/providers`);
      let baseline: string | null = null;
      if (baseRes.ok) {
        const baseData = await baseRes.json();
        baseline = baseData.find((d: any) => d.provider === forcedProvider)?.validated_at ?? null;
      }
      setValidatedAt(null);

      const valRes = await apiFetch(`${apiBase()}/admin/sso/providers/${forcedProvider}/validate/start`, {
        method: "POST",
      });
      if (!valRes.ok) {
        const errData = await valRes.json();
        throw new Error(
          typeof errData.detail === "string" ? errData.detail : "Errore nell'avvio della validazione."
        );
      }

      const { authorize_url } = await valRes.json();

      const popup = window.open(authorize_url, "SSO Validation", "width=600,height=800");

      setVerifying(true);
      let attempts = 0;
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        attempts++;
        const stop = () => {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setVerifying(false);
        };
        try {
          const checkRes = await apiFetch(`${apiBase()}/admin/sso/providers`);
          if (checkRes.ok) {
            const data = await checkRes.json();
            const active = data.find((d: any) => d.provider === forcedProvider);
            if (active && active.validated_at && active.validated_at !== baseline) {
              setValidatedAt(active.validated_at);
              stop();
              popup?.close();
              return;
            }
          }
        } catch (e) { }

        if (popup && popup.closed && attempts > 3) {
          stop();
          setError("Finestra di verifica chiusa prima del completamento.");
          return;
        }
        if (attempts > 90) {
          stop();
          setError("Tempo scaduto per la validazione.");
        }
      }, 2000);

      setSaving(false);

    } catch (err: any) {
      setError(err.message);
      setSaving(false);
      setVerifying(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Caricamento configurazione SSO…
      </div>
    );
  }

  const labelCls = "text-sm font-medium";
  const linkCls = "font-medium underline underline-offset-4 hover:text-foreground";

  return (
    <div className="flex w-full flex-col gap-5 rounded-2xl border border-border/70 bg-card p-5 text-left sm:p-6">
      <div className="rounded-xl bg-secondary/60 px-4 py-3.5 text-sm">
        {forcedProvider === "microsoft" && (
          <div className="flex flex-col gap-2">
            <h4 className="flex items-center gap-2 font-semibold"><Info className="h-4 w-4 text-muted-foreground" aria-hidden /> Come configurare Microsoft Entra ID</h4>
            <ol className="list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
              <li>Vai su <a href="https://entra.microsoft.com/" target="_blank" rel="noreferrer" className={linkCls}>Microsoft Entra admin center</a> &gt; <strong>App registrations</strong> &gt; <strong>New registration</strong>.</li>
              <li>Scegli <strong>Web</strong> come Redirect URI e incolla l'URI fornito qui sotto. Clicca <strong>Register</strong>.</li>
              <li>Dalla pagina <strong>Overview</strong>, copia <em>Application (client) ID</em> e <em>Directory (tenant) ID</em> e incollali qui sotto.</li>
              <li>Vai su <strong>Certificates & secrets</strong>, crea un nuovo <strong>Client secret</strong> e copia il <em>Value</em>.</li>
            </ol>
          </div>
        )}
        {forcedProvider === "google" && (
          <div className="flex flex-col gap-2">
            <h4 className="flex items-center gap-2 font-semibold"><Info className="h-4 w-4 text-muted-foreground" aria-hidden /> Come configurare Google Workspace</h4>
            <ol className="list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
              <li>Vai su <a href="https://console.cloud.google.com/" target="_blank" rel="noreferrer" className={linkCls}>Google Cloud Console</a> e seleziona il tuo progetto.</li>
              <li>Se non l'hai fatto, configura prima la <strong>OAuth consent screen</strong> da <em>APIs & Services</em>.</li>
              <li>Vai su <strong>Credentials</strong> &gt; <strong>+ Create Credentials</strong> &gt; <strong>OAuth client ID</strong> (tipo: Web application).</li>
              <li>In <strong>Authorized redirect URIs</strong> incolla l'URI fornito qui sotto e clicca <strong>Create</strong>.</li>
              <li>Copia <em>Client ID</em> e <em>Client secret</em> mostrati a schermo e incollali qui sotto.</li>
            </ol>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {forcedProvider === "microsoft" && (
          <label className="flex flex-col gap-1.5 md:col-span-2">
            <span className={labelCls}>Directory (tenant) ID</span>
            <input type="text" value={directoryId} onChange={(e) => setDirectoryId(e.target.value)} className={cn(inputCls, "font-mono")} placeholder="es. 82865…" />
          </label>
        )}

        <label className="flex flex-col gap-1.5">
          <span className={labelCls}>Client ID</span>
          <input type="text" value={clientId} onChange={(e) => setClientId(e.target.value)} className={cn(inputCls, "font-mono")} placeholder="Client ID / Application ID" />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className={labelCls}>Client secret</span>
          <input type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} autoComplete="new-password" className={inputCls} placeholder={validatedAt && !clientSecret ? "•••••••• (lascia vuoto per non modificare)" : "Client secret"} />
        </label>

        <label className="flex flex-col gap-1.5 md:col-span-2">
          <span className={labelCls}>
            {forcedProvider === "google" ? "Dominio Google Workspace" : "Dominio Microsoft Entra ID"}
            <span className="font-normal text-muted-foreground"> · opzionale, es. azienda.it</span>
          </span>
          <input type="text" value={allowedDomains} onChange={(e) => setAllowedDomains(e.target.value)} className={inputCls} placeholder="Restringi il login a questo dominio (separa più domini con una virgola)" />
        </label>
      </div>

      <div className="flex flex-col gap-2">
        <h4 className={labelCls}>Redirect URI autorizzato</h4>
        <p className="text-xs text-muted-foreground">
          Copia questo link e incollalo nella configurazione della tua app {forcedProvider === "microsoft" ? "su Azure Portal" : "sulla Google Cloud Console"}.
        </p>
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-xl border border-border bg-background px-3.5 py-2.5 font-mono text-xs">{redirectUri || "…"}</code>
          <button type="button" onClick={handleCopy} className={cn(outlineBtn, "w-9 shrink-0 justify-center px-0")} aria-label={copied ? "Copiato" : "Copia redirect URI"}>
            {copied ? <Check className="h-4 w-4 text-success" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-3 rounded-2xl bg-destructive/10 px-4 py-3 text-sm text-destructive" role="alert">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <div>{error}</div>
        </div>
      )}

      {fresh || (isActive && validatedAt) ? (
        <div className="flex flex-col gap-3">
          {fresh && (
            <div className="flex items-center justify-between gap-3 rounded-2xl bg-success/10 px-4 py-3 text-sm text-success">
            <div className="flex items-center gap-2.5">
              <Check className="h-4 w-4 shrink-0" aria-hidden />
              <span className="font-medium">Configurazione validata</span>
            </div>
            <button type="button" onClick={() => { setValidatedAt(null); }} className="focus-ring rounded-md text-xs font-medium underline underline-offset-4">
              Reimposta
            </button>
          </div>
          )}
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              disabled={saving}
              onClick={async () => {
                setSaving(true);
                try {
                  const domainsList = allowedDomains.split(",").map(d => d.trim()).filter(d => d);
                  const res = await apiFetch(`${apiBase()}/admin/sso/providers/${forcedProvider}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      client_id: clientId,
                      directory_tenant_id: forcedProvider === "microsoft" ? directoryId : undefined,
                      allowed_domains: domainsList.length > 0 ? domainsList : undefined,
                      auto_provision: true,
                      default_roles: ["user"],
                    }),
                  });
                  if (!res.ok) throw new Error("Errore nel salvataggio");
                  fetchProviders(); // Refresh per confermare
                } catch (err: any) {
                  setError(err.message);
                } finally {
                  setSaving(false);
                }
              }}
              className={outlineBtn}
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />} Salva modifiche domini
            </button>
            {!isActive && fresh && (
              <button type="button" onClick={() => onActivate?.()} className={solidBtn}>
                Imposta come predefinito
              </button>
            )}
          </div>
        </div>
      ) : (
        <button
          type="button"
          disabled={saving || verifying || !clientId || (forcedProvider === "microsoft" && !directoryId)}
          onClick={handleSaveAndVerify}
          className={cn(solidBtn, "justify-center sm:self-start")}
        >
          {verifying ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> In attesa della validazione nel popup…
            </>
          ) : (
            <>
              <Shield className="h-3.5 w-3.5" aria-hidden /> Salva e verifica con il mio account
            </>
          )}
        </button>
      )}
    </div>
  );
}
