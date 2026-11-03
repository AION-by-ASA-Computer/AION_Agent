import {
  BarChart3,
  Bot,
  Brain,
  Clock,
  FlaskConical,
  HeartPulse,
  LayoutDashboard,
  MessageCircle,
  Server,
  Settings,
  ShieldCheck,
  Sparkles,
  ThumbsUp,
  Users,
  type LucideIcon,
} from "lucide-react";

/** Admin destinations, shared by the sidebar and the dashboard command bar. */
export type AdminNavItem = {
  id: string;
  href: string;
  icon: LucideIcon;
  /** i18n key for the label (admin_nav.*). */
  labelKey: string;
};

export type AdminNavGroup = {
  id: string;
  /** i18n key for the group heading; null for the ungrouped top entry. */
  labelKey: string | null;
  items: AdminNavItem[];
};

export const ADMIN_NAV: AdminNavGroup[] = [
  {
    id: "home",
    labelKey: null,
    items: [{ id: "dashboard", href: "/", icon: LayoutDashboard, labelKey: "admin_nav.dashboard" }],
  },
  {
    id: "agents",
    labelKey: "admin_nav.groups.agents",
    items: [
      { id: "profiles", href: "/profiles", icon: Bot, labelKey: "admin_nav.profiles" },
      { id: "skills", href: "/skills", icon: Sparkles, labelKey: "admin_nav.skills" },
      { id: "hub", href: "/hub", icon: Server, labelKey: "admin_nav.hub" },
      { id: "memory", href: "/memory", icon: Brain, labelKey: "admin_nav.memory" },
    ],
  },
  {
    id: "operations",
    labelKey: "admin_nav.groups.operations",
    items: [
      { id: "schedules", href: "/schedules", icon: Clock, labelKey: "admin_nav.schedules" },
    ],
  },
  {
    id: "observability",
    labelKey: "admin_nav.groups.observability",
    items: [
      { id: "metrics", href: "/metrics", icon: BarChart3, labelKey: "admin_nav.metrics" },
      { id: "feedback", href: "/feedback", icon: ThumbsUp, labelKey: "admin_nav.feedback" },
      { id: "diagnostics", href: "/diagnostics", icon: FlaskConical, labelKey: "admin_nav.diagnostics" },
      { id: "system", href: "/system", icon: HeartPulse, labelKey: "admin_nav.system" },
    ],
  },
  {
    id: "access",
    labelKey: "admin_nav.groups.access",
    items: [
      { id: "users", href: "/users", icon: Users, labelKey: "admin_nav.users" },
      { id: "security", href: "/security", icon: ShieldCheck, labelKey: "admin_nav.security" },
    ],
  },
  {
    id: "platform",
    labelKey: "admin_nav.groups.platform",
    items: [
      { id: "settings", href: "/settings", icon: Settings, labelKey: "admin_nav.settings" },
      { id: "whatsapp", href: "/whatsapp", icon: MessageCircle, labelKey: "admin_nav.whatsapp" },
    ],
  },
];

export function isNavActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
