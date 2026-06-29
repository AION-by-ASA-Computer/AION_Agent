"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/headers"
import { apiBase } from "@/lib/api";
import { Layers, RefreshCw, Box, Terminal, Activity } from "lucide-react";

export default function PluginsManager() {
  const [plugins, setPlugins] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);

  const fetchPlugins = () => {
    setLoading(true);
    apiFetch(`${apiBase()}/admin/plugins`)
      .then(res => res.ok ? res.json() : Promise.reject(res))
      .then(data => {
        setPlugins(data.plugins || []);
        setLoading(false);
      })
      .catch(err => {
        console.error("Plugins fetch failed", err);
        setPlugins([]);
        setLoading(false);
      });
  };

  const handleReload = () => {
    setReloading(true);
    apiFetch(`${apiBase()}/admin/plugins/reload`, { method: "POST" })
      .then(res => res.json())
      .then(data => {
        alert(`Successfully reloaded ${data.loaded} plugins.`);
        setReloading(false);
        fetchPlugins();
      })
      .catch(() => setReloading(false));
  };

  useEffect(() => {
    fetchPlugins();
  }, []);

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight uppercase text-gray-500 text-sm italic">Logic Extension Hub</h2>
          <p className="text-gray-400 text-sm mt-1">Manage system hooks, event listeners, and runtime plugins.</p>
        </div>
        <button 
          onClick={handleReload}
          disabled={reloading}
          className="flex items-center gap-2 px-4 py-2 bg-[#141414] hover:bg-[#1a1a1a] text-gray-300 border border-[#262626] rounded-xl font-bold transition-all text-xs disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${reloading ? 'animate-spin' : ''}`} /> Hot Reload Plugins
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <h3 className="text-[10px] uppercase font-bold text-gray-500 tracking-widest px-1">Active Runtime Modules</h3>
          <div className="glass-card overflow-hidden border border-[#262626]">
            <div className="divide-y divide-[#262626]">
              {plugins.map((p) => (
                <div key={p} className="p-4 flex items-center justify-between hover:bg-white/[0.01] transition-colors group">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center border border-blue-500/20">
                      <Box className="w-5 h-5 text-blue-500" />
                    </div>
                    <div>
                      <div className="text-sm font-bold text-gray-200">{p}</div>
                      <div className="text-[10px] uppercase font-bold text-gray-500 tracking-tighter">Hook Listener ● data/plugins/{p}.py</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 bg-green-500 rounded-full"></span>
                    <span className="text-[10px] font-bold text-green-500 uppercase tracking-widest">Running</span>
                  </div>
                </div>
              ))}
              {plugins.length === 0 && (
                <div className="p-12 text-center text-gray-500 italic text-sm">
                  No custom plugins detected in data/plugins/.
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <h3 className="text-[10px] uppercase font-bold text-gray-500 tracking-widest px-1">Pipeline Hook Status</h3>
          <div className="glass-card p-5 border border-[#262626] space-y-4">
             {[
               { name: "on_user_message", status: "Active", count: 1 },
               { name: "pre_llm_call", status: "Active", count: 2 },
               { name: "on_assistant_message", status: "Active", count: 1 },
               { name: "pre_tool_use", status: "Inactive", count: 0 }
             ].map(hook => (
               <div key={hook.name} className="flex items-center justify-between">
                 <div className="flex items-center gap-2">
                    <Activity className={`w-3 h-3 ${hook.count > 0 ? 'text-green-500' : 'text-gray-600'}`} />
                    <span className="text-xs font-mono text-gray-400">{hook.name}</span>
                 </div>
                 <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${hook.count > 0 ? 'bg-green-500/10 text-green-500' : 'bg-gray-500/10 text-gray-500'}`}>
                    {hook.count}
                 </span>
               </div>
             ))}
          </div>

          <div className="bg-orange-500/5 border border-orange-500/20 p-5 rounded-2xl">
             <div className="flex items-center gap-2 text-orange-500 font-bold text-[10px] uppercase mb-2">
                <Terminal className="w-3 h-3" /> System Warning
             </div>
             <p className="text-[10px] text-gray-500 leading-relaxed">
                Hot reloading logic can affect active streaming pipelines. Ensure no high-priority tasks are running before a reload.
             </p>
          </div>
        </div>
      </div>
    </div>
  );
}
