"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/cn";
import { MAP_EDGES, type MapColumn, type MapNode, type NodeStatus } from "./derive";

const RANK: Record<NodeStatus, number> = { error: 3, warn: 2, checking: 1, ok: 0, idle: 0 };

export function StatusDot({ status, className }: { status: NodeStatus; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block h-2 w-2 shrink-0 rounded-full",
        status === "ok" && "bg-success",
        status === "warn" && "bg-warning",
        status === "error" && "bg-destructive",
        status === "checking" && "animate-pulse bg-muted-foreground/50",
        status === "idle" && "bg-muted-foreground/30",
        className,
      )}
    />
  );
}

type Edge = { id: string; d: string; status: NodeStatus; kind: "uses" | "contains" };

function MapNodeCard({
  node,
  register,
  highlighted,
}: {
  node: MapNode;
  register: (id: string, el: HTMLElement | null) => void;
  highlighted: boolean;
}) {
  const Icon = node.icon;
  return (
    <Link
      ref={(el) => register(node.id, el)}
      href={node.href}
      className={cn(
        "focus-ring group relative block rounded-2xl border px-3.5 py-3 transition-[border-color,background-color,transform] duration-200",
        highlighted && "-translate-y-0.5 !border-foreground/50",
        node.status === "error"
          ? "border-destructive/60 bg-destructive/[0.07] hover:border-destructive"
          : node.status === "warn"
            ? "border-warning/45 bg-card hover:border-warning/80"
            : "border-border/70 bg-card hover:border-foreground/25 hover:bg-secondary/60",
      )}
    >
      <div className="flex items-center gap-2">
        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-muted-foreground group-hover:text-foreground">
          {node.label}
        </span>
        <StatusDot status={node.status} />
        <span className="sr-only">{node.statusLabel}</span>
      </div>
      {node.value !== null && (
        <div className="mt-1 text-xl font-semibold leading-tight tracking-[-0.01em] tabular-nums">{node.value}</div>
      )}
      <div
        className={cn(
          "mt-0.5 truncate text-xs",
          node.status === "error" ? "text-destructive" : node.status === "warn" ? "text-warning" : "text-muted-foreground",
        )}
        title={node.detail}
      >
        {node.detail}
      </div>
    </Link>
  );
}

export function AgentMap({
  columns,
  title,
  subtitle,
  legend,
  highlight,
}: {
  columns: MapColumn[];
  title: string;
  subtitle: string;
  legend: { uses: string; contains: string };
  /** Node to point at while a related "needs attention" row is hovered. */
  highlight?: string | null;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const nodeEls = useRef(new Map<string, HTMLElement>());
  const [edges, setEdges] = useState<Edge[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });

  const statusOf = useCallback(
    (id: string): NodeStatus => {
      for (const c of columns) for (const n of c.nodes) if (n.id === id) return n.status;
      return "idle";
    },
    [columns],
  );

  const register = useCallback((id: string, el: HTMLElement | null) => {
    if (el) nodeEls.current.set(id, el);
    else nodeEls.current.delete(id);
  }, []);

  const measure = useCallback(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const base = wrap.getBoundingClientRect();
    setSize({ w: base.width, h: base.height });
    const next: Edge[] = [];
    const rect = (id: string) => nodeEls.current.get(id)?.getBoundingClientRect();
    for (const { from, to, kind, over } of MAP_EDGES) {
      const a = rect(from);
      const b = rect(to);
      // Only draw when the columns sit side by side (desktop layout).
      if (!a || !b || a.right + 16 > b.left) continue;
      const x1 = a.right - base.left;
      const y1 = a.top + a.height / 2 - base.top;
      const x2 = b.left - base.left;
      const y2 = b.top + b.height / 2 - base.top;
      let d: string;
      const o = over ? rect(over) : undefined;
      if (o) {
        // Arc over the node in between along a lane just above it, so the line never crosses its card.
        const l = o.left - base.left - 10;
        const r = o.right - base.left + 10;
        const lane = o.top - base.top - 14;
        d = `M${x1} ${y1} C${(x1 + l) / 2} ${y1} ${(x1 + l) / 2} ${lane} ${l} ${lane} L${r} ${lane} C${(r + x2) / 2} ${lane} ${(r + x2) / 2} ${y2} ${x2} ${y2}`;
      } else {
        const mx = (x1 + x2) / 2;
        d = `M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`;
      }
      const sa = statusOf(from);
      const sb = statusOf(to);
      const status = RANK[sa] >= RANK[sb] ? sa : sb;
      next.push({ id: `${from}-${to}-${kind}`, d, status, kind });
    }
    setEdges(next);
  }, [statusOf]);

  useLayoutEffect(() => {
    measure();
    const wrap = wrapRef.current;
    if (!wrap) return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [measure]);

  // Problem edges are drawn last so they sit above the quiet ones.
  const ordered = [...edges].sort((a, b) => RANK[a.status] - RANK[b.status]);

  return (
    <section className="rounded-3xl border border-border/60 bg-card/40 p-4 sm:p-5" aria-labelledby="agent-map-title">
      <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id="agent-map-title" className="text-sm font-semibold">
          {title}
        </h2>
        <p className="text-xs text-muted-foreground">{subtitle}</p>
        <div className="ml-auto hidden items-center gap-4 text-[11.5px] text-muted-foreground lg:flex" aria-hidden>
          <span className="inline-flex items-center gap-1.5">
            <svg width="20" height="2" className="stroke-muted-foreground/70">
              <line x1="0" y1="1" x2="20" y2="1" strokeWidth="1.5" />
            </svg>
            {legend.uses}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <svg width="20" height="2" className="stroke-muted-foreground/70">
              <line x1="0" y1="1" x2="20" y2="1" strokeWidth="1.5" strokeDasharray="2 4" strokeLinecap="round" />
            </svg>
            {legend.contains}
          </span>
        </div>
      </div>
      <div ref={wrapRef} className="relative">
        <svg
          className="pointer-events-none absolute inset-0 hidden lg:block"
          width={size.w}
          height={size.h}
          aria-hidden
        >
          {ordered.map((e) => (
            <path
              key={e.id}
              d={e.d}
              fill="none"
              strokeLinecap="round"
              className={cn(
                e.status === "error"
                  ? "aion-edge-alert stroke-destructive"
                  : e.status === "warn"
                    ? "stroke-warning/70"
                    : "stroke-border",
              )}
              strokeWidth={e.status === "error" || e.status === "warn" ? 1.75 : 1.25}
              strokeDasharray={e.kind === "contains" && e.status !== "error" ? "2 5" : undefined}
            />
          ))}
        </svg>
        <div className="relative grid gap-5 sm:grid-cols-2 lg:grid-cols-5 lg:gap-x-10 xl:gap-x-12">
          {columns.map((col) => (
            <div key={col.id} className="flex flex-col gap-2.5">
              <div className="px-1 text-[10.5px] font-bold uppercase tracking-widest text-muted-foreground/60">
                {col.label}
              </div>
              <div className="flex flex-1 flex-col gap-2.5 lg:justify-center">
                {col.nodes.map((n) => (
                  <MapNodeCard key={n.id} node={n} register={register} highlighted={highlight === n.id} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
