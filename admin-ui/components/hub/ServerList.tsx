"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  ChevronsUpDown,
  Box,
  ExternalLink,
  Globe,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  Settings2,
  Terminal,
  Trash2,
  Wand2,
  Wrench,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { outlineBtn } from "@/components/ui/classes";
import type { IntegrationPolicyRow } from "@/lib/mcpIntegrationPolicy";
import type { McpIntegrityIssue } from "@/components/McpIntegrityBanner";
import { serverStatus, STATUS_RANK, type ServerStatus } from "@/components/hub/useHub";

export interface McpItemRow {
  name: string;
  config: {
    description?: string;
    type?: string;
    is_base?: boolean;
    aion_connector_id?: string;
    command?: string;
    args?: string[];
    url?: string;
    env?: Record<string, string>;
  };
  policy?: IntegrationPolicyRow;
  connector?: Record<string, unknown> | null;
  issues?: McpIntegrityIssue[];
}

type SortKey = "server" | "status" | "runtime" | "credentials";

type Handlers = {
  loading: boolean;
  probingSlug: string | null;
  onEdit: (name: string, config: McpItemRow["config"]) => void;
  onProbe: (name: string) => void;
  onWizard: (name: string) => void;
  onManageTools: (name: string) => void;
  onDelete: (name: string) => void;
  onAdvisor: (name: string) => void;
  advisorUrl: (name: string) => string;
  view?: "table" | "cards";
};

const DOT: Record<ServerStatus, string> = {
  attention: "bg-warning",
  oauth: "bg-warning",
  system: "bg-muted-foreground/60",
  disabled: "bg-muted-foreground/40",
  active: "bg-success",
};

function RowMenu({ item, h, probing }: { item: McpItemRow; h: Handlers; probing: boolean }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const { name, config } = item;
  const isBase = !!config.is_base;
  const remote = config.type === "sse" || config.type === "remote-bridge";

  const toggle = () => {
    if (!open && btn.current) {
      const r = btn.current.getBoundingClientRect();
      const width = 232;
      const height = 280;
      const up = window.innerHeight - r.bottom < height && r.top > window.innerHeight - r.bottom;
      setPos({
        top: up ? Math.max(8, r.top - height - 4) : r.bottom + 6,
        left: Math.max(8, Math.min(window.innerWidth - width - 8, r.right - width)),
      });
    }
    setOpen((v) => !v);
  };

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      const n = e.target as Node;
      if (!menu.current?.contains(n) && !btn.current?.contains(n)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        btn.current?.focus();
      }
    };
    const close = () => setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  const itemCls =
    "focus-ring flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-colors hover:bg-secondary disabled:opacity-50";
  const run = (fn: () => void) => () => {
    setOpen(false);
    fn();
  };

  return (
    <>
      <button
        ref={btn}
        type="button"
        onClick={toggle}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("admin_hub.menu.more", { name })}
        className="focus-ring inline-flex h-9 w-9 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden />
      </button>
      {open &&
        pos &&
        createPortal(
          <div
            ref={menu}
            role="menu"
            style={{ position: "fixed", top: pos.top, left: pos.left }}
            className="z-[100] w-[232px] rounded-2xl border border-border bg-popover p-1.5 text-popover-foreground shadow-[0_18px_40px_-16px_rgba(0,0,0,0.5)]"
          >
            {!isBase && (
              <button type="button" role="menuitem" className={itemCls} disabled={h.loading} onClick={run(() => h.onManageTools(name))}>
                <Wrench className="h-4 w-4 text-muted-foreground" aria-hidden />
                {t("admin_hub.menu.tools")}
              </button>
            )}
            {!isBase && (
              <button type="button" role="menuitem" className={itemCls} disabled={h.loading || probing} onClick={run(() => h.onProbe(name))}>
                {probing ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden /> : <Activity className="h-4 w-4 text-muted-foreground" aria-hidden />}
                {probing ? t("admin_hub.menu.probing") : t("admin_hub.menu.probe")}
              </button>
            )}
            {!isBase && !remote && (
              <button type="button" role="menuitem" className={itemCls} disabled={h.loading} onClick={run(() => h.onWizard(name))}>
                <Wand2 className="h-4 w-4 text-muted-foreground" aria-hidden />
                {t("admin_hub.menu.wizard")}
              </button>
            )}
            <button type="button" role="menuitem" className={itemCls} onClick={run(() => h.onAdvisor(name))}>
              <MessageSquare className="h-4 w-4 text-muted-foreground" aria-hidden />
              {t("admin_hub.menu.advisor")}
            </button>
            <a
              role="menuitem"
              href={h.advisorUrl(name)}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setOpen(false)}
              className={itemCls}
            >
              <ExternalLink className="h-4 w-4 text-muted-foreground" aria-hidden />
              {t("admin_hub.menu.chat")}
            </a>
            {!isBase && (
              <>
                <div className="my-1 h-px bg-border" />
                <button
                  type="button"
                  role="menuitem"
                  className={cn(itemCls, "text-destructive hover:bg-destructive/10")}
                  disabled={h.loading}
                  onClick={run(() => h.onDelete(name))}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                  {t("admin_hub.menu.uninstall")}
                </button>
              </>
            )}
          </div>,
          document.body,
        )}
    </>
  );
}

function hueOf(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return (h * 137) % 360;
}

function monogram(label: string): string {
  const parts = label.split(/[\s_\-./:]+/).filter(Boolean);
  const m = parts.length > 1 ? parts[0][0] + parts[1][0] : label.slice(0, 2);
  return m.toUpperCase();
}

export function ServerList({ items, view = "table", ...h }: { items: McpItemRow[] } & Handlers) {
  const t = useT();
  const k = "admin_hub.list";
  const table = view === "table";
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" } | null>(null);
  const toggleSort = (key: SortKey) =>
    setSort((cur) => (cur?.key !== key ? { key, dir: "asc" } : cur.dir === "asc" ? { key, dir: "desc" } : null));
  const sorted = useMemo(() => {
    if (!sort || !table) return items;
    const val = (it: McpItemRow): string | number => {
      const { name, config, policy } = it;
      switch (sort.key) {
        case "server":
          return (policy?.display_name || name).toLowerCase();
        case "status":
          return STATUS_RANK[serverStatus(it)];
        case "runtime":
          return config.is_base ? "built_in" : config.type || "stdio";
        default:
          return policy?.credential_mode ?? "none";
      }
    };
    const m = sort.dir === "asc" ? 1 : -1;
    return [...items].sort((a, b) => {
      const x = val(a);
      const y = val(b);
      const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
      return c * m || a.name.localeCompare(b.name);
    });
  }, [items, sort, table]);

  return (
    <>
    {table && (
      <div
        role="row"
        className="hidden gap-4 px-5 pb-1 lg:grid lg:grid-cols-[minmax(0,2.2fr)_minmax(0,1.3fr)_minmax(0,1.1fr)_minmax(0,1.1fr)_auto]"
      >
        {(["server", "status", "runtime", "credentials"] as SortKey[]).map((key) => {
          const active = sort?.key === key;
          const Icon = !active ? ChevronsUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
          return (
            <div key={key} role="columnheader" aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
              <button
                type="button"
                onClick={() => toggleSort(key)}
                className={cn(
                  "focus-ring -ml-2 inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium transition-colors hover:bg-secondary hover:text-foreground",
                  active ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {t(`${k}.col_${key}`)}
                <Icon className={cn("h-3 w-3", !active && "opacity-50")} aria-hidden />
              </button>
            </div>
          );
        })}
        <span className="w-[8.5rem]" />
      </div>
    )}
    <ul className={table ? "divide-y divide-border/60 overflow-hidden rounded-3xl border border-border/70 bg-card" : "grid gap-3 md:grid-cols-2 2xl:grid-cols-3"}>
      {sorted.map((item) => {
        const { name, config, policy, issues = [] } = item;
        const status = serverStatus(item);
        const probing = h.probingSlug === name;
        const remote = config.type === "sse" || config.type === "remote-bridge";
        const RuntimeIcon = remote ? Globe : config.type === "in_process" ? Box : Terminal;
        const display = policy?.display_name && policy.display_name !== name ? policy.display_name : null;
        const title = display || name;
        const connectorId = policy?.aion_connector_id || config.aion_connector_id;
        const warn = status === "attention" || status === "oauth";
        const detail = status === "attention" ? issues[0]?.message : config.description || null;
        const runtime = config.is_base
          ? t("admin_hub.runtime.built_in")
          : t(`admin_hub.runtime.${config.type && ["sse", "remote-bridge", "in_process"].includes(config.type) ? config.type : "stdio"}`);
        const scope = t(`admin_hub.scope.${policy?.credential_mode ?? "none"}`);
        const hue = hueOf(connectorId || name);

        const tile = (size: string) => (
          <span
            aria-hidden
            className={cn(
              "flex shrink-0 items-center justify-center font-bold tracking-tight bg-[oklch(0.93_0.06_var(--h))] text-[oklch(0.42_0.14_var(--h))] dark:bg-[oklch(0.32_0.07_var(--h))] dark:text-[oklch(0.86_0.09_var(--h))]",
              size,
            )}
          >
            {probing ? <Loader2 className="h-4 w-4 animate-spin" /> : monogram(title)}
          </span>
        );

        if (table) {
          return (
            <li
              key={name}
              style={{ "--h": hue } as React.CSSProperties}
              className={cn(
                "grid items-center gap-x-4 gap-y-2 px-4 py-3.5 sm:px-5 lg:grid-cols-[minmax(0,2.2fr)_minmax(0,1.3fr)_minmax(0,1.1fr)_minmax(0,1.1fr)_auto]",
                status === "disabled" && "opacity-75",
              )}
            >
              <div className="flex min-w-0 items-center gap-3.5">
                {tile("h-10 w-10 rounded-xl text-[13px]")}
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold">{title}</div>
                  <div className="truncate text-xs text-muted-foreground">{name !== title ? name : detail || connectorId || "\u00a0"}</div>
                </div>
              </div>
              <div className="min-w-0 text-xs font-medium">
                <span className="inline-flex items-center gap-1.5">
                  <span className={cn("h-2 w-2 shrink-0 rounded-full", DOT[status])} aria-hidden />
                  <span className={warn ? "text-warning" : "text-muted-foreground"}>
                    {probing ? t(`${k}.probing`) : t(`admin_hub.status.${status}`)}
                  </span>
                </span>
                {status === "attention" && detail && <p className="mt-0.5 line-clamp-1 font-normal text-warning">{detail}</p>}
              </div>
              <span className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground">
                <RuntimeIcon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="truncate">{runtime}</span>
              </span>
              <span className="truncate text-[13px] text-muted-foreground">{scope}</span>
              <div className="flex items-center gap-1.5 lg:justify-end">
                <button type="button" className={outlineBtn} onClick={() => h.onEdit(name, config)}>
                  <Settings2 className="h-3.5 w-3.5" aria-hidden />
                  {t(`${k}.configure`)}
                </button>
                <RowMenu item={item} h={h} probing={probing} />
              </div>
            </li>
          );
        }

        return (
          <li
            key={name}
            style={{ "--h": hue } as React.CSSProperties}
            className={cn(
              "group relative flex flex-col rounded-2xl border bg-card p-4 transition-colors hover:border-foreground/25",
              warn ? "border-warning/50" : "border-border/70",
              status === "disabled" && "opacity-75",
            )}
          >
            <div className="flex items-start gap-3.5">
              <span
                aria-hidden
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-[15px] font-bold tracking-tight bg-[oklch(0.93_0.06_var(--h))] text-[oklch(0.42_0.14_var(--h))] dark:bg-[oklch(0.32_0.07_var(--h))] dark:text-[oklch(0.86_0.09_var(--h))]"
              >
                {probing ? <Loader2 className="h-5 w-5 animate-spin" /> : monogram(title)}
              </span>
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-[15px] font-semibold tracking-[-0.01em]">{title}</h3>
                <div className="mt-0.5 flex items-center gap-1.5 text-xs font-medium">
                  <span className={cn("h-2 w-2 rounded-full", DOT[status])} aria-hidden />
                  <span className={warn ? "text-warning" : "text-muted-foreground"}>
                    {probing ? t(`${k}.probing`) : t(`admin_hub.status.${status}`)}
                  </span>
                </div>
              </div>
              <RowMenu item={item} h={h} probing={probing} />
            </div>

            <p
              className={cn(
                "mt-3 line-clamp-2 min-h-[2.6rem] text-[13px] leading-relaxed",
                status === "attention" ? "text-warning" : "text-muted-foreground",
              )}
            >
              {detail || "\u00a0"}
            </p>

            <div className="mt-3 flex items-center gap-2 border-t border-border/50 pt-3">
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <RuntimeIcon className="h-3.5 w-3.5" aria-hidden />
                  {runtime}
                </span>
                <span>{scope}</span>
              </div>
              <button type="button" className={outlineBtn} onClick={() => h.onEdit(name, config)}>
                <Settings2 className="h-3.5 w-3.5" aria-hidden />
                {t(`${k}.configure`)}
              </button>
            </div>
            {name !== title && <span className="sr-only">{name}</span>}
          </li>
        );
      })}
    </ul>
    </>
  );
}
