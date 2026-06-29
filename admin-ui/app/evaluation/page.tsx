"use client";

import React from "react";

export default function EvaluationPage() {
  return (
    <div className="p-8 text-gray-500 italic">Visualizzazione Evaluation non disponibile.</div>
  );
}

/*
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/headers"
import { CheckCircle, XCircle, BarChart3, Database } from "lucide-react";
import { apiBase } from "@/lib/api";

export default function OriginalEvaluationPage() {
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const formatDate = (dateStr: string) => {
    try {
      if (!dateStr) return "N/A";
      // Fix format for Safari/some engines (space to T)
      const isoStr = dateStr.replace(" ", "T");
      const d = new Date(isoStr);
      return isNaN(d.getTime()) ? dateStr : d.toLocaleString();
    } catch (e) {
      return dateStr;
    }
  };

  useEffect(() => {
    apiFetch(`${apiBase()}/admin/eval/runs`)
      .then((res) => res.json())
      .then((data) => {
        setRuns(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Error fetching eval runs:", err);
        setLoading(false);
      });
  }, []);

  if (loading) return <div className="p-8">Caricamento storico test...</div>;

  return (
    <div className="p-8 space-y-6">
      <header>
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <BarChart3 className="text-green-500" />
          AION Evaluation Harness
        </h1>
        <p className="text-gray-400 mt-2">Storico delle esecuzioni di test e regressioni.</p>
      </header>

      <div className="overflow-hidden border border-gray-800 rounded-xl bg-gray-900 shadow-2xl">
        <table className="w-full text-left">
          <thead className="bg-gray-800/50 text-gray-400 text-sm">
            <tr>
              <th className="p-4">Run ID</th>
              <th className="p-4">Dataset</th>
              <th className="p-4">Score</th>
              <th className="p-4">Status</th>
              <th className="p-4">Data</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {runs.length === 0 ? (
              <tr>
                <td colSpan={5} className="p-8 text-center text-gray-500 italic">
                  Nessun test eseguito finora.
                </td>
              </tr>
            ) : (
              runs.map((run) => (
                <tr key={run.id} className="hover:bg-gray-800/30 transition-colors">
                  <td className="p-4 font-mono text-blue-400">{run.run_id}</td>
                  <td className="p-4">{run.dataset_name}</td>
                  <td className="p-4 font-bold text-lg">
                    {((run.overall_score || 0) * 100).toFixed(0)}%
                  </td>
                  <td className="p-4">
                    {(run.overall_score || 0) >= 0.8 ? (
                      <span className="flex items-center gap-1 text-green-500">
                        <CheckCircle size={16} /> PASS
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-red-500">
                        <XCircle size={16} /> FAIL
                      </span>
                    )}
                  </td>
                  <td className="p-4 text-gray-500 text-sm">
                    {formatDate(run.created_at)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
*/
