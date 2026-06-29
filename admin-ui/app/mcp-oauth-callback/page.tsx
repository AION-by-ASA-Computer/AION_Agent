"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";

function OAuthCallbackContent() {
  const searchParams = useSearchParams();
  const status = searchParams.get("status");
  const serverSlug = searchParams.get("server_slug");
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const errorParam = searchParams.get("error");

  const [loading, setLoading] = useState(true);
  const [success, setSuccess] = useState<boolean | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    const handleCallback = async () => {
      // Caso 1: il redirect è avvenuto tramite il backend AION (GET /v1/integrations/oauth/callback)
      // che ha già scambiato il token ed ha ridiretto il browser qui con ?status=success o ?status=error
      if (status) {
        setLoading(false);
        if (status === "success") {
          setSuccess(true);
          setTimeout(() => {
            try {
              window.close();
            } catch (e) {
              console.error(e);
            }
          }, 2000);
        } else {
          setSuccess(false);
          setErrorMsg(errorParam || "Errore sconosciuto durante lo scambio OAuth.");
        }
        return;
      }

      // Caso 2: redirect diretto dal provider OAuth (se non abbiamo usato la GET di AION come relay)
      if (code && state) {
        try {
          // Il flusso raccomandato è usare il backend GET callback che fa redirect con ?status=success.
          setSuccess(false);
          setErrorMsg("Flusso OAuth non allineato. Utilizzare il callback del backend.");
          setLoading(false);
        } catch (err: any) {
          setSuccess(false);
          setErrorMsg(err.message || "Errore di connessione.");
          setLoading(false);
        }
        return;
      }

      // Caso 3: Nessun parametro atteso
      setLoading(false);
      setSuccess(false);
      setErrorMsg("Nessun codice di autorizzazione o stato trovato.");
    };

    handleCallback();
  }, [status, code, state, errorParam, serverSlug]);

  return (
    <div className="flex flex-col items-center justify-center p-8 space-y-6 text-center max-w-md w-full bg-[#1a1a1a] border border-white/10 rounded-3xl shadow-2xl">
      {loading ? (
        <div className="flex flex-col items-center space-y-4">
          <Loader2 className="w-16 h-16 text-indigo-500 animate-spin" />
          <h2 className="text-xl font-bold text-white">Connessione in corso</h2>
          <p className="text-sm text-gray-400">
            Stiamo scambiando le credenziali con l'applicazione remota...
          </p>
        </div>
      ) : success ? (
        <div className="flex flex-col items-center space-y-4">
          <CheckCircle2 className="w-16 h-16 text-green-500" />
          <h2 className="text-xl font-bold text-white">Connessione completata!</h2>
          <p className="text-sm text-gray-400">
            Il modulo {serverSlug ? `«${serverSlug}»` : ""} è stato configurato con successo.
          </p>
          <p className="text-xs text-gray-500">
            Questa finestra si chiuderà automaticamente tra pochi secondi.
          </p>
        </div>
      ) : (
        <div className="flex flex-col items-center space-y-4">
          <XCircle className="w-16 h-16 text-red-500" />
          <h2 className="text-xl font-bold text-white font-mono text-red-400">Connessione Fallita</h2>
          <div className="w-full bg-black/40 border border-red-500/20 rounded-2xl p-4 text-left max-h-48 overflow-y-auto">
            <p className="text-xs font-mono text-red-300 break-words leading-relaxed">
              {errorMsg}
            </p>
          </div>
          <p className="text-sm text-gray-400">
            Chiudi questa finestra e riprova l'autenticazione dall'Hub.
          </p>
        </div>
      )}

      <button
        type="button"
        onClick={() => {
          try {
            window.close();
          } catch (e) {
            console.error(e);
          }
        }}
        className="px-6 py-2.5 w-full bg-white/5 hover:bg-white/10 border border-white/10 text-white rounded-xl text-sm font-bold transition-all cursor-pointer"
      >
        Chiudi finestra
      </button>
    </div>
  );
}

export default function OAuthCallbackPage() {
  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white flex items-center justify-center p-4">
      <Suspense fallback={
        <div className="flex flex-col items-center space-y-4">
          <Loader2 className="w-16 h-16 text-indigo-500 animate-spin" />
          <h2 className="text-xl font-bold text-white">Caricamento…</h2>
        </div>
      }>
        <OAuthCallbackContent />
      </Suspense>
    </div>
  );
}
