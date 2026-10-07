"use client";

import { useEffect, useState } from "react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { Shield, Copy, Check, AlertTriangle, ExternalLink, Loader2, Info, Save } from "lucide-react";

export function SsoConfigPanel({
  forcedProvider,
  onValidationSuccess,
  isActive,
}: {
  forcedProvider: "microsoft" | "google";
  onValidationSuccess?: () => void;
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

  useEffect(() => {
    fetchProviders();
  }, [forcedProvider]);

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
    let base = window.location.origin;
    if (base.includes(":3870")) {
      base = base.replace(":3870", ":8001");
    } else if (base.includes(":8003")) {
      base = base.replace(":8003", ":8001");
    }
    const uri = `${base}/auth/sso/callback`;
    navigator.clipboard.writeText(uri);
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

      setValidatedAt(null);

      const valRes = await apiFetch(`${apiBase()}/admin/sso/providers/${forcedProvider}/validate/start`, {
        method: "POST",
      });
      if (!valRes.ok) {
        const errData = await valRes.json();
        throw new Error(errData.detail || "Errore nell'avvio della validazione.");
      }

      const { authorize_url } = await valRes.json();

      const popup = window.open(authorize_url, "SSO Validation", "width=600,height=800");

      setVerifying(true);
      let attempts = 0;
      const interval = setInterval(async () => {
        attempts++;
        try {
          const checkRes = await apiFetch(`${apiBase()}/admin/sso/providers`);
          if (checkRes.ok) {
            const data = await checkRes.json();
            const active = data.find((d: any) => d.provider === forcedProvider);
            if (active && active.validated_at) {
              setValidatedAt(active.validated_at);
              clearInterval(interval);
              setVerifying(false);
              popup?.close();
              onValidationSuccess?.();
            }
          }
        } catch (e) { }

        if (attempts > 90) {
          clearInterval(interval);
          setVerifying(false);
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
    return <div className="text-sm text-gray-400 animate-pulse">Caricamento configurazione SSO...</div>;
  }

  return (
    <div className="space-y-6 w-full text-left p-6 rounded-xl border border-[#222] bg-[#070707]">
      <div className="space-y-6">

        <div className="p-4 rounded-xl bg-blue-500/5 border border-blue-500/20 text-sm text-gray-300">
          {forcedProvider === "microsoft" && (
            <div className="space-y-2">
              <h4 className="font-bold text-white flex items-center gap-2"><Info className="w-4 h-4 text-blue-400" /> Come configurare Microsoft Entra ID</h4>
              <ol className="list-decimal pl-5 space-y-1 text-xs text-gray-400">
                <li>Vai su <a href="https://entra.microsoft.com/" target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">Microsoft Entra admin center</a> &gt; <strong>App registrations</strong> &gt; <strong>New registration</strong>.</li>
                <li>Scegli <strong>Web</strong> come Redirect URI e incolla l'URI fornito qui sotto. Clicca <strong>Register</strong>.</li>
                <li>Dalla pagina <strong>Overview</strong>, copia <em>Application (client) ID</em> e <em>Directory (tenant) ID</em> e incollali qui sotto.</li>
                <li>Vai su <strong>Certificates & secrets</strong>, crea un nuovo <strong>Client secret</strong> e copia il <em>Value</em>.</li>
              </ol>
            </div>
          )}
          {forcedProvider === "google" && (
            <div className="space-y-2">
              <h4 className="font-bold text-white flex items-center gap-2"><Info className="w-4 h-4 text-blue-400" /> Come configurare Google Workspace</h4>
              <ol className="list-decimal pl-5 space-y-1 text-xs text-gray-400">
                <li>Vai su <a href="https://console.cloud.google.com/" target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">Google Cloud Console</a> e seleziona il tuo progetto.</li>
                <li>Se non l'hai fatto, configura prima la <strong>OAuth consent screen</strong> da <em>APIs & Services</em>.</li>
                <li>Vai su <strong>Credentials</strong> &gt; <strong>+ Create Credentials</strong> &gt; <strong>OAuth client ID</strong> (tipo: Web application).</li>
                <li>In <strong>Authorized redirect URIs</strong> incolla l'URI fornito qui sotto e clicca <strong>Create</strong>.</li>
                <li>Copia <em>Client ID</em> e <em>Client secret</em> mostrati a schermo e incollali qui sotto.</li>
              </ol>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {forcedProvider === "microsoft" && (
            <div className="space-y-2 md:col-span-2">
              <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Directory (tenant) ID</label>
              <input type="text" value={directoryId} onChange={(e) => setDirectoryId(e.target.value)} className="w-full bg-black border border-[#333] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all" placeholder="es. 82865..." />
            </div>
          )}

          <div className="space-y-2 md:col-span-1">
            <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Client ID</label>
            <input type="text" value={clientId} onChange={(e) => setClientId(e.target.value)} className="w-full bg-black border border-[#333] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all" placeholder="Client ID / Application ID" />
          </div>

          <div className="space-y-2 md:col-span-1">
            <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Client Secret</label>
            <input type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} className="w-full bg-black border border-[#333] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all" placeholder={validatedAt && !clientSecret ? "•••••••••••• (lascia vuoto per non modificare)" : "Client Secret"} />
          </div>

          <div className="space-y-2 md:col-span-2">
            <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">
              {forcedProvider === "google" ? "Dominio Google Workspace" : "Dominio Microsoft Entra ID"} (opzionale, es. azienda.it)
            </label>
            <input type="text" value={allowedDomains} onChange={(e) => setAllowedDomains(e.target.value)} className="w-full bg-black border border-[#333] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all" placeholder="Restringi il login solo a questo dominio (o separati da virgola)" />
          </div>
        </div>

        <div className="p-4 rounded-xl bg-blue-500/5 border border-blue-500/20 space-y-2">
          <h4 className="text-xs font-bold text-blue-400 uppercase tracking-wider flex items-center gap-2">
            <ExternalLink className="w-4 h-4" /> Redirect URI Autorizzato
          </h4>
          <p className="text-xs text-gray-400">
            Copia questo link e incollalo nella configurazione della tua app {forcedProvider === "microsoft" ? "su Azure Portal" : "sulla Google Cloud Console"}.
          </p>
          <div className="flex gap-2 items-center">
            <code className="flex-1 bg-black p-2 rounded text-xs text-blue-300 font-mono truncate border border-[#333]">
              {typeof window !== 'undefined' && (window.location.origin.includes(":3870") || window.location.origin.includes(":8003")
                ? window.location.origin.replace(/:3870$/, ":8001").replace(/:8003$/, ":8001")
                : window.location.origin)}
              /auth/sso/callback
            </code>
            <button type="button" onClick={handleCopy} className="p-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors">
              {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
            </button>
          </div>
        </div>

        {error && (
          <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 flex items-start gap-3 text-sm">
            <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
            <div>{error}</div>
          </div>
        )}

        {validatedAt ? (
            <div className="space-y-4">
              <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-between text-sm">
                <div className="flex items-center gap-3">
                  <Check className="w-5 h-5 shrink-0" />
                  <span className="font-semibold">Configurazione validata con successo!</span>
                </div>
                <button type="button" onClick={() => { setValidatedAt(null); }} className="text-xs underline hover:text-emerald-300">
                  Reimposta
                </button>
              </div>
              <div className="flex gap-3">
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
                  className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl font-bold transition-all bg-[#222] text-white hover:bg-[#333]"
                >
                  {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />} Salva Modifiche Domini
                </button>
                {!isActive && (
                  <button
                    type="button"
                    onClick={() => onValidationSuccess?.()}
                    className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl font-bold transition-all bg-emerald-600 text-white hover:bg-emerald-500"
                  >
                    Imposta come Predefinito
                  </button>
                )}
              </div>
            </div>
        ) : (
          <button
            type="button"
            disabled={saving || verifying || !clientId || (forcedProvider === "microsoft" && !directoryId)}
            onClick={handleSaveAndVerify}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl font-bold transition-all bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {verifying ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" /> In attesa della validazione nel popup...
              </>
            ) : (
              <>
                <Shield className="w-5 h-5" /> Salva e verifica con il mio account
              </>
            )}
          </button>
        )}

      </div>
    </div>
  );
}
