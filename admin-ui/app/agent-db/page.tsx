"use client";

import React from "react";

export default function AgentDBOverview() {
  return (
    <div className="p-8 text-gray-500 italic">Visualizzazione Agent DB non disponibile.</div>
  );
}

/*
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/headers"
import Link from "next/link";
import { apiBase } from "@/lib/api";
import { Database, Search, RefreshCw, ChevronRight } from "lucide-react";

interface UserDBStats {
  user_id: string;
  schema_count: number;
  table_count: number;
  row_count: number;
  size_bytes: number;
  last_modified: string | null;
}

export default function OriginalAgentDBOverview() {
  const [stats, setStats] = useState<UserDBStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      const resp = await apiFetch(`${apiBase()}/admin/agent-db/overview`);
      if (!resp.ok) throw new Error("Failed to fetch overview");
      const data = await resp.json();
      setStats(data);
      setError(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const formatSize = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  return (
    <div className="bg-[#0a0a0a] min-h-screen text-white">
      <div className="max-w-6xl mx-auto">
        <header className="mb-12 flex justify-between items-end">
          <div>
            <h1 className="text-4xl font-bold tracking-tight mb-2 bg-gradient-to-r from-white to-gray-500 bg-clip-text text-transparent">
              Agent DB Explorer
            </h1>
            <p className="text-gray-400">Monitor and manage autonomous user databases.</p>
          </div>
          <button
            onClick={fetchData}
            className="flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm hover:bg-white/10 transition-all"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </header>

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 text-red-500 p-4 rounded-xl mb-8">
            Error: {error}
          </div>
        )}

        <div className="grid gap-6">
          <div className="bg-[#111] border border-white/10 rounded-2xl overflow-hidden">
            <div className="p-6 border-b border-white/5 bg-white/[0.02] flex justify-between items-center">
              <h2 className="text-xl font-semibold flex items-center gap-3">
                <Database className="w-5 h-5 text-blue-500" />
                Active Databases
              </h2>
              <div className="text-xs text-gray-500">
                {stats.length} Users with active DBs
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-white/5 text-gray-500 text-[10px] uppercase tracking-widest font-bold">
                    <th className="px-6 py-4">User ID</th>
                    <th className="px-6 py-4">Schemas</th>
                    <th className="px-6 py-4">Tables</th>
                    <th className="px-6 py-4">Total Rows</th>
                    <th className="px-6 py-4">Disk Size</th>
                    <th className="px-6 py-4">Last Activity</th>
                    <th className="px-6 py-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {loading && stats.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-6 py-12 text-center text-gray-500 italic">
                        Loading database stats...
                      </td>
                    </tr>
                  ) : stats.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-6 py-12 text-center text-gray-500 italic">
                        No agent databases found yet.
                      </td>
                    </tr>
                  ) : stats.map((user) => (
                    <tr key={user.user_id} className="hover:bg-white/[0.02] transition-colors group">
                      <td className="px-6 py-4">
                        <div className="font-mono text-sm text-blue-400">{user.user_id}</div>
                      </td>
                      <td className="px-6 py-4 text-sm">{user.schema_count}</td>
                      <td className="px-6 py-4 text-sm">{user.table_count}</td>
                      <td className="px-6 py-4 text-sm font-mono">{user.row_count.toLocaleString()}</td>
                      <td className="px-6 py-4 text-sm text-gray-400">{formatSize(user.size_bytes)}</td>
                      <td className="px-6 py-4 text-sm text-gray-500">
                        {user.last_modified ? new Date(user.last_modified).toLocaleString() : "N/A"}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <Link
                          href={`/agent-db/${user.user_id}`}
                          className="inline-flex items-center gap-2 px-4 py-2 bg-white text-black rounded-lg text-xs font-bold hover:bg-gray-200 transition-all opacity-0 group-hover:opacity-100"
                        >
                          Explore
                          <ChevronRight className="w-3 h-3" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
*/
