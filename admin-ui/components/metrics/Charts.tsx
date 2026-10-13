"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";
import type { TimeSeriesDataPoint } from "./types";

interface ChartProps {
  data?: TimeSeriesDataPoint[];
  label: string;
  stamp: (ts: string) => string;
  format: (v: number) => string;
  /** Tailwind text colour class; strokes and fills follow currentColor. */
  tone?: string;
}

const W = 280;
const H = 44;

function Tip({ at, stamp, value }: { at: number; stamp: string; value: string }) {
  return (
    <div
      className="pointer-events-none absolute -top-8 z-20 -translate-x-1/2 whitespace-nowrap rounded-lg border border-border bg-popover px-2 py-1 text-[11px] text-popover-foreground shadow-lg"
      style={{ left: `${Math.min(88, Math.max(12, at * 100))}%` }}
    >
      <span className="text-muted-foreground">{stamp}</span> <span className="font-semibold tabular-nums">{value}</span>
    </div>
  );
}

function Empty() {
  return <div className="h-11 w-full rounded-lg bg-secondary/50" aria-hidden />;
}

/** Continuous series (token volume, latency): a line with a faint area under it. */
export function TrendChart({ data, label, stamp, format, tone = "text-foreground" }: ChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  if (!data || data.length === 0) return <Empty />;

  const values = data.map((d) => d.value);
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  const pts = data.map((d, i) => ({
    x: 3 + (i / (data.length - 1 || 1)) * (W - 6),
    y: H - 4 - ((d.value - min) / span) * (H - 10),
  }));
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const area = `${line} L${pts[pts.length - 1].x} ${H} L${pts[0].x} ${H} Z`;
  const active = hover !== null ? pts[hover] : null;

  return (
    <div className={cn("relative h-11 w-full", tone)}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full overflow-visible" role="img" aria-label={label} onMouseLeave={() => setHover(null)}>
        <path d={area} fill="currentColor" opacity={0.08} />
        <path d={line} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" opacity={0.85} />
        {pts.map((p, i) => (
          <rect key={i} x={p.x - W / (data.length * 2)} y={0} width={W / data.length} height={H} fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
        {active && <line x1={active.x} x2={active.x} y1={0} y2={H} stroke="currentColor" strokeWidth={1} strokeDasharray="2 3" vectorEffect="non-scaling-stroke" opacity={0.4} />}
      </svg>
      {active && hover !== null && <Tip at={active.x / W} stamp={stamp(data[hover].timestamp)} value={format(data[hover].value)} />}
    </div>
  );
}

/** Counted series (turns, tool calls): one bar per bucket. */
export function BarsChart({ data, label, stamp, format, tone = "text-foreground" }: ChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  if (!data || data.length === 0) return <Empty />;

  const max = Math.max(...data.map((d) => d.value), 1);
  const gap = 2;
  const bw = Math.max(2, (W - gap * (data.length - 1)) / data.length);

  return (
    <div className={cn("relative h-11 w-full", tone)}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full overflow-visible" role="img" aria-label={label} onMouseLeave={() => setHover(null)}>
        {data.map((d, i) => {
          const h = Math.max(2, (d.value / max) * (H - 4));
          return <rect key={i} x={i * (bw + gap)} y={H - h} width={bw} height={h} rx={1.5} fill="currentColor" opacity={hover === i ? 1 : 0.55} onMouseEnter={() => setHover(i)} />;
        })}
      </svg>
      {hover !== null && <Tip at={(hover * (bw + gap) + bw / 2) / W} stamp={stamp(data[hover].timestamp)} value={format(data[hover].value)} />}
    </div>
  );
}
