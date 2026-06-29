"use client";

import React from "react";

export default function ProfilingPage() {
  return (
    <div className="p-8 text-gray-500 italic">Visualizzazione Profiling non disponibile.</div>
  );
}

/*
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/headers"
import { Activity, AlertTriangle, Clock, Server } from "lucide-react";
import { apiBase } from "@/lib/api";

export default function OriginalProfilingPage() {
  const [bottlenecks, setBottlenecks] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch(`${apiBase()}/admin/profiling/bottlenecks`)
      .then((res) => res.json())
      .then((data) => {
        setBottlenecks(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Error fetching bottlenecks:", err);
        setLoading(false);
      });
  }, []);

  if (loading) return <div className="p-8 text-gray-400">Caricamento report...</div>;

  return (
    <div className="p-8 space-y-6">
      <header>
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Activity className="text-blue-500" />
          AION Profiling & Bottlenecks
        </h1>
        <p className="text-gray-400 mt-2">Analisi automatizzata delle performance basata sull'euristica V3.</p>
      </header>

      {!bottlenecks || bottlenecks.error ? (
        <div className="bg-yellow-900/20 border border-yellow-700/50 p-4 rounded-lg flex items-center gap-3">
          <AlertTriangle className="text-yellow-500" />
          Nessun dato di profilazione trovato o errore nella richiesta. Esegui qualche turno con l'agente per generare i log.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-gray-900 border border-gray-800 p-6 rounded-xl shadow-xl">
            <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
              <Server className="text-purple-500" />
              Diagnosi Primaria
            </h2>
            <div className="text-2xl font-bold text-white mb-2">
              {bottlenecks.status === "ok" ? "Sistema Ottimale" : "Collo di Bottiglia Rilevato"}
            </div>
            <p className="text-gray-400">
              {bottlenecks.analysis || "Tutto sembra girare correttamente."}
            </p>
          </div>

          <div className="bg-gray-900 border border-gray-800 p-6 rounded-xl shadow-xl">
            <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
              <Clock className="text-green-500" />
              Latenze Medie
            </h2>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span>LLM (Inference)</span>
                <span className="font-mono text-blue-400">{(bottlenecks.avg_llm || 0).toFixed(2)}s</span>
              </div>
              <div className="flex justify-between">
                <span>Tools (MCP)</span>
                <span className="font-mono text-purple-400">{(bottlenecks.avg_tools || 0).toFixed(2)}s</span>
              </div>
              <div className="flex justify-between">
                <span>Memory (RAG)</span>
                <span className="font-mono text-green-400">{(bottlenecks.avg_memory || 0).toFixed(2)}s</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
*/
