"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/headers"
import { apiBase } from "@/lib/api";
import { Server, Database, HardDrive, RefreshCw } from "lucide-react";

export default function SystemHealth() {
  const [health, setHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const fetchHealth = () => {
    setLoading(true);
    apiFetch(`${apiBase()}/admin/system/health`)
      .then(res => res.json())
      .then(data => {
        setHealth(data);
        setLoading(false);
      })
      .catch(err => {
        console.error("Health fetch failed", err);
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading && !health) {
    return <div className="animate-pulse text-gray-500 uppercase text-xs font-bold tracking-widest">Scanning System...</div>;
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight uppercase text-gray-500 text-sm italic">Infrastructure Integrity</h2>
          <p className="text-gray-400 text-sm mt-1">Real-time status of AION Agent V2 core components.</p>
        </div>
        <button 
          onClick={fetchHealth}
          className="p-2 hover:bg-[#141414] rounded-lg border border-[#262626] transition-all group"
        >
          <RefreshCw className={`w-4 h-4 text-gray-400 group-hover:text-blue-500 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Redis Status */}
        <div className="glass-card p-6 border border-[#262626] bg-[#141414]/40">
          <div className="flex items-center gap-3 mb-6">
            <div className={`p-2 rounded-lg ${health?.redis?.connected ? 'bg-green-500/10 text-green-500' : 'bg-red-500/10 text-red-500'}`}>
              <Server className="w-5 h-5" />
            </div>
            <div>
              <div className="text-sm font-bold">Redis Cluster</div>
              <div className="text-[10px] uppercase text-gray-500 font-bold tracking-tighter">Shared State Management</div>
            </div>
          </div>
          
          <div className="space-y-4">
            <div className="flex justify-between items-center text-xs">
              <span className="text-gray-500">Status</span>
              <span className={`font-bold ${health?.redis?.connected ? 'text-green-500' : 'text-red-500'}`}>
                {health?.redis?.connected ? 'OPERATIONAL' : 'OFFLINE'}
              </span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-gray-500">Type</span>
              <span className="text-gray-300 font-medium">{health?.redis?.type}</span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-gray-500">Fallback</span>
              <span className={`font-bold ${health?.redis?.fallback_active ? 'text-orange-500' : 'text-gray-400'}`}>
                {health?.redis?.fallback_active ? 'ACTIVE' : 'INACTIVE'}
              </span>
            </div>
            <div className="pt-2 border-t border-[#262626]">
              <div className="text-[10px] text-gray-600 truncate">{health?.redis?.url}</div>
            </div>
          </div>
        </div>

        {/* Database Status */}
        <div className="glass-card p-6 border border-[#262626] bg-[#141414]/40">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 rounded-lg bg-blue-500/10 text-blue-500">
              <Database className="w-5 h-5" />
            </div>
            <div>
              <div className="text-sm font-bold">Unified Data Layer</div>
              <div className="text-[10px] uppercase text-gray-500 font-bold tracking-tighter">SQLAlchemy 2.x Engine</div>
            </div>
          </div>
          
          <div className="space-y-4">
            <div className="flex justify-between items-center text-xs">
              <span className="text-gray-500">Engine</span>
              <span className="text-gray-300 font-medium">Aiosqlite / SQLite</span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-gray-500">Unified DB</span>
              <span className={`font-bold ${health?.database?.unified ? 'text-green-500' : 'text-red-500'}`}>
                {health?.database?.unified ? 'ENABLED' : 'DISABLED'}
              </span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-gray-500">Storage Size</span>
              <span className="text-gray-300 font-medium">
                {health?.database?.size_bytes > 0 
                  ? `${(health.database.size_bytes / 1024 / 1024).toFixed(2)} MB` 
                  : 'N/A'}
              </span>
            </div>
            <div className="pt-2 border-t border-[#262626]">
              <div className="text-[10px] text-gray-600 truncate">{health?.database?.url}</div>
            </div>
          </div>
        </div>

        {/* Storage Backend */}
        <div className="glass-card p-6 border border-[#262626] bg-[#141414]/40">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 rounded-lg bg-purple-500/10 text-purple-500">
              <HardDrive className="w-5 h-5" />
            </div>
            <div>
              <div className="text-sm font-bold">Object Storage</div>
              <div className="text-[10px] uppercase text-gray-500 font-bold tracking-tighter">Hybrid Backend Architecture</div>
            </div>
          </div>
          
          <div className="space-y-4">
            <div className="flex justify-between items-center text-xs">
              <span className="text-gray-500">Active Backend</span>
              <span className="text-purple-500 font-bold uppercase">{health?.storage?.backend}</span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-gray-500">Local Root</span>
              <span className="text-gray-300 font-medium">{health?.storage?.local_root}</span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-gray-500">Redundancy</span>
              <span className="text-gray-400">Standard</span>
            </div>
            <div className="pt-2 border-t border-[#262626]">
              <div className="text-[10px] text-gray-600 truncate">V2 Platform Hybrid Storage Enabled</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
