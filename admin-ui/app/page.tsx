"use client";

import { ArrowRight, Shield, Zap, Globe, Users } from "lucide-react";
import { apiFetch } from "@/lib/api/headers"
import { useEffect, useState } from "react";
import { apiBase } from "@/lib/api";
import Link from "next/link";

export default function Home() {
  const [stats, setStats] = useState<any>(null);

  useEffect(() => {
    apiFetch(`${apiBase()}/admin/stats`)
      .then(res => res.json())
      .then(data => setStats(data))
      .catch(err => console.error("Stats fetch failed", err));
  }, []);

  const statItems = [
    { name: "Active Profiles", value: stats?.active_profiles || "...", icon: Users, color: "text-blue-500", href: "/profiles" },
    { name: "Total Skills", value: stats?.total_skills || "...", icon: Zap, color: "text-purple-500", href: "/skills" },
    { name: "Installed MCPs", value: stats?.installed_mcp || "...", icon: Globe, color: "text-green-500", href: "/hub" },
    { name: "Global Security", value: stats?.security_score || "...", icon: Shield, color: "text-orange-500", href: "/security" },
  ];

  return (
    <div className="space-y-8">
      <section>
        <h2 className="text-3xl font-bold tracking-tight mb-2 uppercase text-gray-500 text-sm italic">System Overview</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mt-6">
          {statItems.map((stat) => (
            <Link key={stat.name} href={stat.href} className="glass-card p-6 border border-[#262626] bg-[#141414]/40 hover:border-blue-500/30 transition-all group">
              <div className="flex items-center justify-between mb-4">
                <stat.icon className={`w-6 h-6 ${stat.color} group-hover:scale-110 transition-transform`} />
                <span className="text-[10px] text-green-500 font-bold bg-green-500/10 px-2 py-0.5 rounded uppercase">Real-time</span>
              </div>
              <div className="text-3xl font-bold tracking-tighter">{stat.value}</div>
              <div className="text-xs font-bold uppercase text-gray-500 mt-2 tracking-widest">{stat.name}</div>
            </Link>
          ))}
        </div>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <h2 className="text-xs font-bold uppercase text-gray-500 px-1 tracking-wider">Recent System Integrity Checks</h2>
          <div className="glass-card overflow-hidden">
            <div className="divide-y divide-[#262626]">
              {[
                { name: "Prometheus Monitoring", time: "2 mins ago" },
                { name: "Grafana Dashboards", time: "1 hour ago" },
                { name: "AION Memory Sync", time: "3 hours ago" }
              ].map((scan, i) => (
                <div key={i} className="p-4 flex items-center justify-between hover:bg-white/[0.02] transition-colors group">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-xl bg-green-500/10 flex items-center justify-center border border-green-500/20 group-hover:bg-green-500/20 transition-all">
                      <Shield className="w-5 h-5 text-green-500" />
                    </div>
                    <div>
                      <div className="text-sm font-bold text-gray-200">Security Scan: {scan.name}</div>
                      <div className="text-[10px] uppercase font-bold text-gray-500 tracking-tighter">Verified by AION Antivirus ● {scan.time}</div>
                    </div>
                  </div>
                  <div className="text-[10px] font-bold px-2 py-1 bg-green-500/10 text-green-500 rounded border border-green-500/20">
                    PASS
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <h2 className="text-xs font-bold uppercase text-gray-500 px-1 tracking-wider">Operational Directives</h2>
          <div className="space-y-3">
            <Link href="/profiles" className="w-full flex items-center justify-between px-5 py-4 bg-blue-600 hover:bg-blue-700 text-white rounded-2xl font-bold transition-all shadow-lg shadow-blue-600/20 text-sm">
              Initialize New Identity <ArrowRight className="w-4 h-4" />
            </Link>
            <Link href="/hub" className="w-full flex items-center justify-between px-5 py-4 bg-[#0d0d0d] hover:bg-[#141414] border border-[#262626] text-gray-300 rounded-2xl font-bold transition-all text-sm">
              Provision MCP Server <ArrowRight className="w-4 h-4" />
            </Link>
            <Link href="/skills" className="w-full flex items-center justify-between px-5 py-4 bg-[#0d0d0d] hover:bg-[#141414] border border-[#262626] text-gray-300 rounded-2xl font-bold transition-all text-sm">
              Refactor Protocols <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
