"use client";

/**
 * Inline chart rendering for chat turns.
 *
 * Charts come from the `charts` MCP tools (backend: `src/main.py` interception →
 * `chart` SSE event → `session_charts` table). `TurnTimeline` renders one
 * `ChartBlock` per `{kind: "chart"}` segment, live while the model is still
 * streaming and again from the history after a reload.
 *
 * Layout: the block fills the chat column (which already shrinks when side
 * panels open) and is centered in it; its height follows its own width
 * (ResizeObserver), so the plot keeps a readable aspect ratio on any screen.
 * Colors use the `--chart-1..8` theme tokens (validated categorical palette,
 * light/dark variants in `styles/theme-tokens.css`).
 */

import { memo, useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BarChart3, Table2 } from "lucide-react";

import type { ChartPayload } from "@/lib/sse/types";
import { useT } from "@/lib/i18n/use-t";
import { cn } from "@/lib/cn";

/** Fixed categorical order: series N always gets slot N (never cycled by rank). */
const SERIES_VARS = [
  "--chart-1",
  "--chart-2",
  "--chart-3",
  "--chart-4",
  "--chart-5",
  "--chart-6",
  "--chart-7",
  "--chart-8",
] as const;

/** Past the palette size series fold onto muted ink instead of a generated hue. */
function seriesColor(index: number): string {
  return index < SERIES_VARS.length
    ? `hsl(var(${SERIES_VARS[index]}))`
    : "hsl(var(--muted-foreground))";
}

/** Plot height derived from the measured width: ~2:1, clamped for phones and wide screens. */
const MIN_PLOT_H = 220;
const MAX_PLOT_H = 420;
const PLOT_RATIO = 0.5;

const tooltipStyle = {
  background: "hsl(var(--popover))",
  border: "1px solid hsl(var(--border))",
  borderRadius: "calc(var(--radius) - 4px)",
  color: "hsl(var(--popover-foreground))",
  fontSize: 12,
  boxShadow: "0 8px 24px -12px rgb(0 0 0 / 0.35)",
};

const axisTick = { fill: "hsl(var(--muted-foreground))", fontSize: 11 };

function seriesKeysForChart(chart: ChartPayload, rows: Array<Record<string, unknown>>): string[] {
  if (!rows.length) return [];
  const xk = chart.x_key || "index";
  const all = Object.keys(rows[0]).filter((k) => k !== xk);
  const sk = chart.series_keys;
  if (sk?.length) return sk.filter((k) => all.includes(k));
  return all;
}

/** Compact number formatting for axis ticks (1.2k, 3.4M) — tooltips keep full values. */
function formatTick(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value ?? "");
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

/** Measure an element's content width (re-measured when side panels open/close). */
function useElementWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      setWidth((prev) => (Math.abs(prev - w) >= 1 ? w : prev));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

function ChartBody({
  chart,
  rows,
  compact,
}: {
  chart: ChartPayload;
  rows: Array<Record<string, unknown>>;
  compact: boolean;
}) {
  const xKey = chart.x_key || "index";
  const cols = seriesKeysForChart(chart, rows);
  const kind = chart.chart_kind || "line";
  const stackId = chart.stacked ? "stack" : undefined;
  // Legend only when it identifies something (>= 2 series), and not if disabled.
  const showLegend = !chart.legend_off && cols.length > 1;
  const margin = { top: 8, right: compact ? 8 : 16, bottom: 4, left: 0 };

  const commonAxes = (
    <>
      <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeOpacity={0.7} />
      <XAxis
        dataKey={xKey}
        tick={axisTick}
        tickLine={false}
        axisLine={{ stroke: "hsl(var(--border))" }}
        minTickGap={compact ? 16 : 24}
        tickMargin={6}
      />
      <YAxis
        tick={axisTick}
        tickLine={false}
        axisLine={false}
        tickFormatter={formatTick}
        width={chart.y_label ? 56 : 44}
        label={
          chart.y_label && !compact
            ? {
                value: chart.y_label,
                angle: -90,
                position: "insideLeft",
                fill: "hsl(var(--muted-foreground))",
                fontSize: 11,
                style: { textAnchor: "middle" },
              }
            : undefined
        }
      />
      <Tooltip
        contentStyle={tooltipStyle}
        labelStyle={{ color: "hsl(var(--muted-foreground))", marginBottom: 4 }}
        itemStyle={{ color: "hsl(var(--popover-foreground))", padding: 0 }}
        cursor={
          kind === "bar"
            ? { fill: "hsl(var(--muted))", fillOpacity: 0.5 }
            : { stroke: "hsl(var(--muted-foreground))", strokeDasharray: "3 3" }
        }
      />
      {showLegend ? (
        <Legend
          verticalAlign="bottom"
          iconType="circle"
          iconSize={8}
          wrapperStyle={{ fontSize: 12, color: "hsl(var(--muted-foreground))", paddingTop: 8 }}
        />
      ) : null}
    </>
  );

  if (kind === "bar") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={margin} barCategoryGap="20%" barGap={2}>
          {commonAxes}
          {cols.map((col, ci) => (
            <Bar
              key={col}
              dataKey={col}
              stackId={stackId}
              fill={seriesColor(ci)}
              // 2px surface gap between adjacent / stacked fills
              stroke="hsl(var(--background))"
              strokeWidth={stackId ? 1 : 0}
              radius={stackId ? 0 : [4, 4, 0, 0]}
              maxBarSize={48}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (kind === "area") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={margin}>
          {commonAxes}
          {cols.map((col, ci) => (
            <Area
              key={col}
              type="monotone"
              dataKey={col}
              stackId={stackId}
              stroke={seriesColor(ci)}
              fill={seriesColor(ci)}
              fillOpacity={stackId ? 0.55 : 0.18}
              strokeWidth={2}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "hsl(var(--background))" }}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={rows} margin={margin}>
        {commonAxes}
        {cols.map((col, ci) => (
          <Line
            key={col}
            type="monotone"
            dataKey={col}
            stroke={seriesColor(ci)}
            dot={rows.length <= 24 ? { r: 2.5, strokeWidth: 0, fill: seriesColor(ci) } : false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "hsl(var(--background))" }}
            strokeWidth={2}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Accessible table view of the chart data (also the relief for low-contrast hues). */
function ChartTable({ chart, rows }: { chart: ChartPayload; rows: Array<Record<string, unknown>> }) {
  const xKey = chart.x_key || "index";
  const cols = [xKey, ...seriesKeysForChart(chart, rows)];
  return (
    <div className="max-h-[420px] overflow-auto rounded-md border border-border/60">
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0 bg-muted/80 backdrop-blur">
          <tr>
            {cols.map((c) => (
              <th key={c} className="px-3 py-1.5 text-left font-medium text-muted-foreground">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-border/40">
              {cols.map((c) => (
                <td key={c} className="px-3 py-1 tabular-nums text-foreground">
                  {String(r[c] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * One chart card, centered and full-width within the chat column.
 * Used by `TurnTimeline` for `{kind: "chart"}` segments.
 */
export const ChartBlock = memo(function ChartBlock({
  chart,
  className,
}: {
  chart: ChartPayload;
  className?: string;
}) {
  const t = useT();
  const [view, setView] = useState<"chart" | "table">("chart");
  const [plotRef, plotWidth] = useElementWidth<HTMLDivElement>();
  const rows = useMemo(
    () => (Array.isArray(chart.data) ? chart.data : []) as Array<Record<string, unknown>>,
    [chart.data],
  );
  const title = chart.query?.trim() || t("chat.chart.untitled");
  const kind = chart.chart_kind || "line";
  const plotHeight = Math.round(
    Math.min(MAX_PLOT_H, Math.max(MIN_PLOT_H, (plotWidth || 640) * PLOT_RATIO)),
  );
  const compact = plotWidth > 0 && plotWidth < 480;

  return (
    <figure
      className={cn(
        "aion-chart-block mx-auto my-1 w-full min-w-0 overflow-hidden rounded-aion border border-border/70 bg-card/60 shadow-xs",
        className,
      )}
      aria-label={t("chat.chart.aria", { title })}
    >
      <figcaption className="flex items-start gap-2 border-b border-border/50 px-4 py-2.5">
        <BarChart3 className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground" title={title}>
            {title}
          </p>
          <p className="text-xs text-muted-foreground">
            {t(`chat.chart.kind.${kind}`)} · {t("chat.chart.rows", { count: rows.length })}
          </p>
        </div>
        {rows.length > 0 ? (
          <button
            type="button"
            onClick={() => setView((v) => (v === "chart" ? "table" : "chart"))}
            className="focus-ring inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-pressed={view === "table"}
          >
            {view === "chart" ? <Table2 className="size-3.5" aria-hidden /> : <BarChart3 className="size-3.5" aria-hidden />}
            {view === "chart" ? t("chat.chart.show_table") : t("chat.chart.show_chart")}
          </button>
        ) : null}
      </figcaption>
      <div className="px-2 pb-3 pt-3 sm:px-3">
        <div ref={plotRef} className="w-full min-w-0">
          {rows.length === 0 ? (
            <div
              className="flex items-center justify-center text-xs text-muted-foreground"
              style={{ height: MIN_PLOT_H }}
            >
              {t("chat.chart.no_data")}
            </div>
          ) : view === "table" ? (
            <ChartTable chart={chart} rows={rows} />
          ) : (
            <div className="w-full" style={{ height: plotHeight }}>
              <ChartBody chart={chart} rows={rows} compact={compact} />
            </div>
          )}
        </div>
      </div>
    </figure>
  );
});

/** Renders a list of charts (kept for callers that still show a chart batch). */
export function SessionCharts({ charts }: { charts: ChartPayload[] }) {
  if (!charts.length) return null;
  return (
    <div className="space-y-4">
      {charts.map((chart, i) => (
        <ChartBlock key={chart.id || i} chart={chart} />
      ))}
    </div>
  );
}
