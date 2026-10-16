"use client";

import { Component, type ReactNode } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useT } from "@/lib/i18n/use-t";

type Row = Record<string, unknown>;
export interface SessionChart {
  query?: string;
  title?: string;
  chart_kind?: string;
  chartType?: string;
  kind?: string;
  data?: Row[] | string;
  rows?: Row[] | string;
  x_key?: string;
  xAxisKey?: string;
  series_keys?: string[] | string;
  series?: string[] | string;
  y_label?: string;
  stacked?: boolean;
  legend_off?: boolean;
}

// Series ride the theme tokens so charts follow light/dark with the rest of the admin.
const SERIES = ["hsl(var(--primary))", "hsl(var(--success))", "hsl(var(--warning))", "hsl(var(--destructive))", "hsl(var(--muted-foreground))"];
const AXIS = "hsl(var(--muted-foreground))";

const tooltipStyle = {
  background: "hsl(var(--popover))",
  border: "1px solid hsl(var(--border))",
  borderRadius: 12,
  color: "hsl(var(--popover-foreground))",
  fontSize: 12,
};

function parseRows(chart: SessionChart): Row[] {
  let raw = chart.data ?? chart.rows ?? [];
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(raw)) return raw && typeof raw === "object" ? [raw as Row] : [];
  return raw.filter((r): r is Row => r !== null && typeof r === "object");
}

function seriesKeys(chart: SessionChart, rows: Row[]): string[] {
  const xk = chart.x_key || chart.xAxisKey || "index";
  const all = Object.keys(rows[0]).filter((k) => k !== xk);
  let wanted = chart.series_keys ?? chart.series;
  if (typeof wanted === "string") wanted = wanted.split(",").map((s) => s.trim());
  if (Array.isArray(wanted)) {
    const hit = wanted.filter((k) => all.includes(k));
    if (hit.length) return hit;
  }
  return all.filter((k) => {
    const v = rows[0][k];
    return typeof v === "number" || (v !== "" && v !== null && !Number.isNaN(Number(v)));
  });
}

const compact = (v: unknown) =>
  typeof v === "number" ? (v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}k` : String(v)) : String(v);

function Body({ chart, rows }: { chart: SessionChart; rows: Row[] }) {
  const t = useT();
  const cols = seriesKeys(chart, rows);
  if (cols.length === 0) return <Note>{t("admin_diagnostics.charts.no_numeric")}</Note>;

  const kind = (chart.chart_kind || chart.chartType || chart.kind || "line").toLowerCase();
  const xKey = chart.x_key || chart.xAxisKey || Object.keys(rows[0])[0] || "index";
  const stackId = chart.stacked ? "stack" : undefined;
  const color = (i: number) => SERIES[i % SERIES.length];

  const axes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
      <XAxis dataKey={xKey} stroke={AXIS} fontSize={11} tickLine={false} axisLine={false} minTickGap={8} />
      <YAxis
        stroke={AXIS}
        fontSize={11}
        tickLine={false}
        axisLine={false}
        width={chart.y_label ? 48 : 38}
        tickFormatter={compact}
        label={chart.y_label ? { value: chart.y_label, angle: -90, position: "insideLeft", fill: AXIS, fontSize: 11 } : undefined}
      />
      <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: "hsl(var(--border))" }} />
      {!chart.legend_off && <Legend wrapperStyle={{ fontSize: 12, color: AXIS }} />}
    </>
  );

  return (
    <ResponsiveContainer width="100%" height="100%">
      {kind === "bar" ? (
        <BarChart data={rows}>
          {axes}
          {cols.map((c, i) => <Bar key={c} dataKey={c} stackId={stackId} fill={color(i)} radius={[4, 4, 0, 0]} />)}
        </BarChart>
      ) : kind === "area" ? (
        <AreaChart data={rows}>
          {axes}
          {cols.map((c, i) => <Area key={c} type="monotone" dataKey={c} stackId={stackId} stroke={color(i)} fill={color(i)} fillOpacity={0.15} strokeWidth={2} />)}
        </AreaChart>
      ) : (
        <LineChart data={rows}>
          {axes}
          {cols.map((c, i) => <Line key={c} type="monotone" dataKey={c} stroke={color(i)} dot={{ r: 2.5 }} strokeWidth={2} />)}
        </LineChart>
      )}
    </ResponsiveContainer>
  );
}

function Note({ children }: { children: ReactNode }) {
  return <div className="flex h-full items-center justify-center px-4 text-center text-sm text-muted-foreground">{children}</div>;
}

class Boundary extends Component<{ children: ReactNode; label: (e: string) => string }, { error?: string }> {
  state: { error?: string } = {};
  static getDerivedStateFromError(e: unknown) {
    return { error: String((e as Error)?.message || e) };
  }
  render() {
    return this.state.error !== undefined ? (
      <div role="alert" className="rounded-2xl bg-warning/10 px-4 py-3 text-sm text-warning">{this.props.label(this.state.error)}</div>
    ) : (
      this.props.children
    );
  }
}

export function SessionCharts({ charts }: { charts: SessionChart[] }) {
  const t = useT();
  if (!Array.isArray(charts) || charts.length === 0) return null;
  return (
    <div className="flex flex-col gap-4">
      {charts.map((chart, i) => {
        if (!chart || typeof chart !== "object") return null;
        const rows = parseRows(chart);
        return (
          <Boundary key={i} label={(e) => t("admin_diagnostics.charts.render_error", { error: e })}>
            <figure className="rounded-2xl border border-border bg-card/40 p-4">
              <figcaption className="mb-3 text-sm font-medium">{chart.title || chart.query || t("admin_diagnostics.charts.fallback_title", { n: i + 1 })}</figcaption>
              <div className="h-56 w-full">
                {rows.length === 0 ? <Note>{t("admin_diagnostics.charts.no_data")}</Note> : <Body chart={chart} rows={rows} />}
              </div>
            </figure>
          </Boundary>
        );
      })}
    </div>
  );
}
