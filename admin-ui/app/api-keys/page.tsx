"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { Key, Plus, Trash2, Shield, Clock, ExternalLink, X, AlertTriangle, Check } from "lucide-react";
import { PageToast, ToastState } from "@/components/PageToast";

export default function ApiKeys() {
  const [keys, setKeys] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newKeyData, setNewKeyData] = useState({ name: "", scopes: ["chat:scoped"] });
  const [generatedKey, setGeneratedKey] = useState<any>(null);

  const [toast, setToast] = useState<ToastState>(null);
  const [isRevokeModalOpen, setIsRevokeModalOpen] = useState(false);
  const [keyToRevoke, setKeyToRevoke] = useState<any>(null);
  const [revoking, setRevoking] = useState(false);

  const fetchKeys = () => {
    setLoading(true);
    apiFetch(`${apiBase()}/admin/api-keys`)
      .then(res => res.ok ? res.json() : Promise.reject(res))
      .then(data => {
        setKeys(data.keys || []);
        setLoading(false);
      })
      .catch(err => {
        console.error("API keys fetch failed", err);
        setKeys([]);
        setLoading(false);
        setToast({ message: "Impossibile caricare le API keys.", variant: "error" });
      });
  };

  useEffect(() => {
    fetchKeys();
  }, []);

  const openIssueForm = () => {
    setNewKeyData({ name: "", scopes: ["chat:scoped"] });
    setShowCreate(true);
  };

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyData.name.trim()) {
      setToast({ message: "Inserisci un nome valido per la credenziale.", variant: "error" });
      return;
    }
    setLoading(true);

    apiFetch(`${apiBase()}/admin/api-keys`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(newKeyData)
    })
      .then(res => res.ok ? res.json() : Promise.reject(res))
      .then(data => {
        setGeneratedKey(data);
        setShowCreate(false);
        setNewKeyData({ name: "", scopes: ["chat:scoped"] });
        fetchKeys();
        setToast({ message: "Credenziale generata con successo!", variant: "success" });
      })
      .catch(err => {
        console.error("Creazione fallita", err);
        setToast({ message: "Errore nella generazione della credenziale.", variant: "error" });
        setLoading(false);
      });
  };

  const handleRevokeClick = (key: any) => {
    setKeyToRevoke(key);
    setIsRevokeModalOpen(true);
  };

  const executeRevoke = (id: string) => {
    setRevoking(true);
    apiFetch(`${apiBase()}/admin/api-keys/${id}`, { method: "DELETE" })
      .then(res => res.ok ? res : Promise.reject(res))
      .then(() => {
        setToast({ message: "Credenziale revocata con successo.", variant: "success" });
        setIsRevokeModalOpen(false);
        setKeyToRevoke(null);
        fetchKeys();
      })
      .catch(err => {
        console.error("Revoca fallita", err);
        setToast({ message: "Errore durante la revoca della credenziale.", variant: "error" });
      })
      .finally(() => {
        setRevoking(false);
      });
  };

  return (
    <div className="space-y-8 pb-12">
      {/* Header */}
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-6">
        <div className="space-y-1">
          <h2 className="text-3xl font-extrabold tracking-tight text-white">API Credentials</h2>
          <p className="text-md text-gray-400 max-w-xl mt-2">
            Manage programmatic access, security credentials, and API permission scopes.
          </p>
        </div>
        <button 
          onClick={openIssueForm}
          className="flex items-center gap-2 px-5 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold text-sm shadow-lg shadow-blue-500/20 transition-all transform active:scale-95 cursor-pointer"
        >
          <Plus className="w-4 h-4" /> ISSUE NEW CREDENTIAL
        </button>
      </header>

      {generatedKey && (
        <div className="glass-card p-6 sm:p-8 border border-blue-500/30 bg-gradient-to-r from-blue-500/10 to-indigo-500/10 rounded-3xl space-y-4 relative overflow-hidden animate-in fade-in zoom-in-95 duration-200 shadow-xl">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-blue-500/20 border border-blue-500/30 rounded-xl text-blue-400">
                <Shield className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">Credential Generated Successfully</h3>
                <p className="text-xs text-gray-400">Copy this secret key now. It will not be displayed again.</p>
              </div>
            </div>
            <button 
              onClick={() => setGeneratedKey(null)}
              className="p-2 text-gray-500 hover:text-white hover:bg-white/5 rounded-xl transition-colors cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="bg-black/60 p-4 rounded-2xl border border-blue-500/20 font-mono text-sm text-blue-400 break-all select-all flex items-center justify-between gap-4">
            <span>{generatedKey.key}</span>
          </div>
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-3xl w-full max-w-2xl overflow-hidden shadow-2xl animate-in zoom-in-95 duration-200 flex flex-col max-h-[90vh]">
            <div className="p-6 border-b border-white/10 flex justify-between items-center bg-white/5 shrink-0">
              <div className="flex items-center gap-3">
                <div className="p-2.5 bg-blue-500/10 border border-blue-500/20 rounded-xl text-blue-400">
                  <Key className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white">Issue New API Credential</h3>
                  <p className="text-xs text-gray-400">Specify credential name and permission scopes</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="p-2 text-gray-500 hover:text-white hover:bg-white/5 rounded-xl transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreate} className="flex flex-col flex-1 overflow-hidden">
              <div className="p-6 space-y-6 overflow-y-auto custom-scrollbar flex-1">
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-wider text-gray-400 flex items-center justify-between">
                    <span>Credential Name</span>
                    <span className="text-[10px] text-gray-600 lowercase font-mono">identifier</span>
                  </label>
                  <input 
                    autoFocus
                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all shadow-inner font-semibold"
                    placeholder="e.g. Mobile App Backend"
                    value={newKeyData.name}
                    onChange={e => setNewKeyData({...newKeyData, name: e.target.value})}
                    required
                  />
                </div>

                <div className="space-y-3">
                  <label className="text-xs font-bold uppercase tracking-wider text-gray-400">Permissions (Scopes)</label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                    {[
                      "conversations:read",
                      "conversations:write",
                      "chat",
                      "chat:scoped",
                      "files:read",
                      "files:write",
                      "admin"
                    ].map(scope => {
                      const isSelected = newKeyData.scopes.includes(scope);
                      return (
                        <div 
                          key={scope} 
                          onClick={() => {
                            const nextScopes = isSelected 
                              ? newKeyData.scopes.filter(s => s !== scope)
                              : [...newKeyData.scopes, scope];
                            setNewKeyData({...newKeyData, scopes: nextScopes});
                          }}
                          className={`p-3 rounded-xl border cursor-pointer transition-all flex items-center justify-between ${
                            isSelected 
                              ? 'bg-blue-500/15 border-blue-500/50 text-blue-300 shadow-sm' 
                              : 'bg-black/30 border-white/5 text-gray-400 hover:border-white/15 hover:bg-black/50 hover:text-gray-200'
                          }`}
                        >
                          <span className="text-xs font-bold uppercase tracking-wider font-mono">{scope}</span>
                          {isSelected ? <Check className="w-4 h-4 text-blue-400" /> : <Plus className="w-4 h-4 opacity-30" />}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              <div className="p-6 border-t border-white/10 flex justify-end gap-3 bg-black/20 shrink-0">
                <button 
                  type="button" 
                  onClick={() => setShowCreate(false)} 
                  className="px-5 py-2.5 bg-white/5 hover:bg-white/10 text-gray-300 hover:text-white border border-white/10 rounded-xl text-sm font-semibold transition-all cursor-pointer"
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  disabled={loading}
                  className="px-6 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold text-sm transition-all shadow-lg shadow-blue-500/20 cursor-pointer transform active:scale-98 disabled:opacity-50 flex items-center gap-2"
                >
                  <Key className="w-4 h-4" /> GENERATE SECURE CREDENTIAL
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className="glass-card overflow-hidden border border-white/10 rounded-3xl bg-gradient-to-b from-[#181818]/90 to-[#121212]/90 shadow-2xl relative">
        <table className="w-full text-left">
          <thead>
            <tr className="bg-black/40 border-b border-white/10">
              <th className="px-6 py-4 text-xs uppercase font-bold text-gray-400 tracking-wider">Identifier</th>
              <th className="px-6 py-4 text-xs uppercase font-bold text-gray-400 tracking-wider">Name</th>
              <th className="px-6 py-4 text-xs uppercase font-bold text-gray-400 tracking-wider">Scopes</th>
              <th className="px-6 py-4 text-xs uppercase font-bold text-gray-400 tracking-wider">Last Used</th>
              <th className="px-6 py-4 text-xs uppercase font-bold text-gray-400 tracking-wider text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {keys.map((key) => (
              <tr key={key.id} className="hover:bg-white/[0.02] transition-colors group">
                <td className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center border border-blue-500/20 text-blue-400 shadow-inner">
                      <Key className="w-5 h-5" />
                    </div>
                    <div>
                      <div className="text-sm font-mono text-white font-bold">{key.prefix}...</div>
                      <div className="text-[10px] text-gray-500 uppercase tracking-wider mt-0.5">{key.tenant_id}</div>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4 text-sm font-semibold text-gray-200">{key.name}</td>
                <td className="px-6 py-4">
                  <div className="flex flex-wrap gap-1.5">
                    {key.scopes.map((s: string) => (
                      <span key={s} className="text-[10px] font-bold px-2.5 py-1 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20 uppercase tracking-wider font-mono shadow-sm">
                        {s}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-6 py-4 text-xs text-gray-400 font-medium">
                  {key.last_used_at ? (
                    <span className="flex items-center gap-1.5">
                      <Clock className="w-3.5 h-3.5 text-gray-500" />
                      {new Date(key.last_used_at).toLocaleDateString()}
                    </span>
                  ) : (
                    <span className="text-gray-600 italic">Never used</span>
                  )}
                </td>
                <td className="px-6 py-4 text-right">
                  <button 
                    onClick={() => handleRevokeClick(key)}
                    title="Revoke Credential"
                    className="p-2.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 rounded-xl transition-all hover:border-red-500/40 cursor-pointer inline-flex items-center justify-center"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {keys.length === 0 && !loading && (
          <div className="p-12 text-center flex flex-col items-center justify-center space-y-3">
            <Key className="w-10 h-10 text-gray-600" />
            <p className="text-sm font-semibold text-gray-400">No active credentials found</p>
            <p className="text-xs text-gray-600 max-w-sm">Generate a new API credential above to enable programmatic access to the platform.</p>
          </div>
        )}
      </div>

      {isRevokeModalOpen && keyToRevoke && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl w-full max-w-xl overflow-hidden shadow-2xl animate-in zoom-in-95 duration-200">
            <div className="p-6 border-b border-white/10 flex justify-between items-center bg-white/5">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <Trash2 className="w-5 h-5 text-red-400" />
                Conferma Revoca Chiave
              </h2>
              <button
                onClick={() => setIsRevokeModalOpen(false)}
                className="text-gray-500 hover:text-white transition-colors cursor-pointer"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-300 text-sm leading-relaxed">
                <p className="font-semibold mb-1 text-lg flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
                  <span className="text-white font-bold">ATTENZIONE: operazione irreversibile</span>
                </p>
                Stai per revocare definitivamente l'API key <b className="text-white font-mono">{keyToRevoke.name}</b> ({keyToRevoke.prefix}...). Qualsiasi applicazione o servizio che la utilizza perderà immediatamente l'accesso.
              </div>
            </div>

            <div className="p-6 border-t border-white/10 flex justify-end gap-3 bg-black/20">
              <button
                onClick={() => setIsRevokeModalOpen(false)}
                className="px-5 py-2.5 text-sm font-semibold text-gray-400 hover:text-white transition-colors cursor-pointer"
              >
                Annulla
              </button>
              <button
                onClick={() => executeRevoke(keyToRevoke.id)}
                disabled={revoking}
                className="bg-red-600 hover:bg-red-500 text-white px-6 py-2.5 rounded-xl text-sm font-bold transition-all flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-red-600/20 cursor-pointer"
              >
                <Trash2 className="w-4 h-4" />
                {revoking ? "Revoca in corso..." : "Revoca Credenziale"}
              </button>
            </div>
          </div>
        </div>
      )}

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}

