"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Users,
  Zap,
  ShieldCheck,
  Settings,
  Globe,
  Brain,
  Layers,
  ClipboardList,
  Activity,
  BarChart3,
  Database,
  LogOut,
  KeyRound,
  Plug2,
  Clock,
  MessageSquare,
} from "lucide-react";
import { apiBase } from "@/lib/api";
import { adminPath } from "@/lib/paths";
import { getStoredUserId, setStoredAuth } from "@/lib/auth/storage";
import { resetAuthStatusCache } from "@/lib/auth/status";
import { AdminBrand } from "@/components/brand/AdminBrand";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "";
  const [embedded, setEmbedded] = React.useState(false);
  const [userId, setUserId] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const v = new URLSearchParams(window.location.search).get("embedded") === "1";
    setEmbedded(v);
    setUserId(getStoredUserId());
  }, [pathname]);
  const isDbEditor = pathname.startsWith("/agent-db/");
  const isAuthPage = pathname === "/login" || pathname === "/change-password" || pathname === "/first-setup";
  const hideChrome = embedded && isDbEditor;

  if (hideChrome) {
    return <main className="h-screen overflow-auto bg-[#0a0a0a] p-2">{children}</main>;
  }
  if (isAuthPage) {
    // Auth pages (login / change-password): no sidebar, full screen.
    return <main className="h-screen w-screen overflow-auto bg-[#0a0a0a]">{children}</main>;
  }

  function logout() {
    setStoredAuth(null, null);
    resetAuthStatusCache();
    window.location.replace(adminPath("/login"));
  }

  const navItems = [
    { name: "Dashboard", href: "/", icon: LayoutDashboard },
    { name: "Users Management", href: "/users", icon: Users },
    { name: "Agent Profiles", href: "/profiles", icon: Users },
    { name: "Skill Registry", href: "/skills", icon: Zap },
    { name: "MCP Hub", href: "/hub", icon: Globe },
    { name: "Conversations", href: "/conversations", icon: ClipboardList },
    { name: "Feedback", href: "/feedback", icon: MessageSquare },
    { name: "Scheduled jobs", href: "/schedules", icon: Clock },
    { name: "API Keys", href: "/api-keys", icon: ShieldCheck },
    { name: "Memory", href: "/memory", icon: Brain },
    { name: "Plugins & Hooks", href: "/plugins", icon: Layers },
    { name: "Security Audit", href: "/security", icon: ShieldCheck },
    // { name: "Approvals", href: "/approvals", icon: ClipboardList },
    // { name: "Agent DB", href: "/agent-db", icon: Database },
    // { name: "Profiling", href: "/profiling", icon: Activity },
    // { name: "Evaluation", href: "/evaluation", icon: BarChart3 },
    { name: "System Health", href: "/system", icon: LayoutDashboard },
    { name: "Settings", href: "/settings", icon: Settings },
  ];

  return (
    <>
      <aside className="w-64 border-r border-[#262626] flex flex-col p-4 bg-[#0a0a0a]">
        <div className="mb-8 px-4 flex min-h-[32px] items-center gap-2 sm:min-w-0">
          <AdminBrand />
        </div>
        <nav className="flex-1 space-y-1">
          {navItems.map((item) => {
            const isActive =
              item.href === "/"
                ? pathname === "/"
                : pathname === item.href || pathname.startsWith(`${item.href}/`);

            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-4 py-2 text-md rounded-lg transition-all ${isActive
                  ? "text-white bg-[#1e1e1e] font-medium border-l-4 border-blue-600"
                  : "text-gray-400 hover:text-white hover:bg-[#141414]"
                  }`}
              >
                <item.icon className="w-4 h-4" />
                {item.name}
              </Link>
            );
          })}
        </nav>
        <div className="pt-3 mt-2 border-t border-[#262626] space-y-1">
          {userId && (
            <div className="px-4 py-1.5 text-md text-gray-500">
              Signed in as <span className="text-gray-300">{userId}</span>
            </div>
          )}
          <Link
            href="/change-password"
            className="flex items-center gap-3 px-4 py-2 text-md text-gray-400 hover:text-white hover:bg-[#141414] rounded-lg transition-all"
          >
            <KeyRound className="w-4 h-4" />
            Change password
          </Link>
          <button
            type="button"
            onClick={logout}
            className="w-full flex items-center gap-3 px-4 py-2 text-md text-gray-400 hover:text-white hover:bg-[#141414] rounded-lg transition-all"
          >
            <LogOut className="w-4 h-4" />
            Logout
          </button>
          <div className="pt-2 text-md text-gray-600 px-4">v1.0.0 Production Ready</div>
        </div>
      </aside>
      <main className="flex-1 overflow-auto bg-[#0a0a0a]">
        <header className="h-16 border-b border-[#262626] flex items-center justify-between px-8 bg-[#0a0a0a]/50 backdrop-blur-md sticky top-0 z-10">
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
              <span className="text-gray-400">API: <span className="text-gray-100 font-medium">{apiBase()}</span></span>
            </div>
          </div>
        </header>
        <div className="p-8 w-full max-w-[96rem] mx-auto">{children}</div>
      </main>
    </>
  );
}

