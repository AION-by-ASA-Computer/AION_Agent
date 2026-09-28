"use client";

import React, { Component, ReactNode } from "react";
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

export interface SessionChart {
  query?: string;
  title?: string;
  chart_kind?: "line" | "bar" | "area" | string;
  chartType?: "line" | "bar" | "area" | string;
  kind?: "line" | "bar" | "area" | string;
  data?: Array<Record<string, unknown>> | string;
  rows?: Array<Record<string, unknown>> | string;
  x_key?: string;
  xAxisKey?: string;
  series_keys?: string[] | string;
  series?: string[] | string;
  y_label?: string;
  stacked?: boolean;
  legend_off?: boolean;
}

const LINE_COLORS = ["#3b82f6", "#10b981", "#8b5cf6", "#f59e0b", "#ec4899", "#06b6d4"] as const;

const tooltipStyle = {
  background: "#141414",
  border: "1px solid #333",
  borderRadius: "8px",
  color: "#ededed",
  fontSize: 11,
};

function parseChartRows(chart: SessionChart): Array<Record<string, unknown>> {
  let raw = chart.data ?? chart.rows ?? [];
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(raw)) {
    if (raw && typeof raw === "object") {
      return [raw as Record<string, unknown>];
    }
    return [];
  }
  return raw.filter((r): r is Record<string, unknown> => r !== null && typeof r === "object");
}

function seriesKeysForChart(chart: SessionChart, rows: Array<Record<string, unknown>>): string[] {
  if (!Array.isArray(rows) || !rows.length || !rows[0]) return [];
  const xk = chart.x_key || chart.xAxisKey || "index";
  const all = Object.keys(rows[0]).filter((k) => k !== xk);
  
  let skRaw = chart.series_keys ?? chart.series;
  if (typeof skRaw === "string") {
    skRaw = skRaw.includes(",") ? skRaw.split(",").map((s) => s.trim()) : [skRaw.trim()];
  }
  
  if (Array.isArray(skRaw) && skRaw.length > 0) {
    const matched = skRaw.filter((k) => typeof k === "string" && all.includes(k));
    if (matched.length > 0) return matched;
  }
  
  return all.filter((k) => {
    const val = rows[0][k];
    return typeof val === "number" || (!isNaN(Number(val)) && val !== "" && val !== null);
  });
}

function ChartBody({ chart, rows }: { chart: SessionChart; rows: Array<Record<string, unknown>> }) {
  if (!rows || rows.length === 0 || !rows[0]) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-gray-500">
        No valid numerical data available for chart
      </div>
    );
  }

  const xKey = chart.x_key || chart.xAxisKey || Object.keys(rows[0])[0] || "index";
  const cols = seriesKeysForChart(chart, rows);
  const kind = (chart.chart_kind || chart.chartType || chart.kind || "line").toLowerCase();
  const stacked = Boolean(chart.stacked);
  const stackId = stacked ? "stack" : undefined;
  const showLegend = !chart.legend_off;

  if (cols.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-gray-500">
        No numerical series detected in data
      </div>
    );
  }

  const commonAxes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
      <XAxis
        dataKey={xKey}
        stroke="#888"
        fontSize={10}
        tickLine={false}
        minTickGap={8}
      />
      <YAxis
        stroke="#888"
        fontSize={10}
        tickLine={false}
        width={chart.y_label ? 44 : 36}
        tickFormatter={(val) =>
          typeof val === "number"
            ? val >= 1000000
              ? `${(val / 1000000).toFixed(1)}M`
              : val >= 1000
              ? `${(val / 1000).toFixed(0)}k`
              : String(val)
            : val
        }
        label={
          chart.y_label
            ? {
                value: chart.y_label,
                angle: -90,
                position: "insideLeft",
                fill: "#888",
                fontSize: 10,
              }
            : undefined
        }
      />
      <Tooltip contentStyle={tooltipStyle} />
      {showLegend ? (
        <Legend wrapperStyle={{ fontSize: 11, color: "#888" }} />
      ) : null}
    </>
  );

  const seriesLines = cols.map((col, ci) => (
    <Line
      key={col}
      type="monotone"
      dataKey={col}
      stroke={LINE_COLORS[ci % LINE_COLORS.length]}
      dot={{ r: 2.5 }}
      strokeWidth={2}
    />
  ));

  const seriesAreas = cols.map((col, ci) => (
    <Area
      key={col}
      type="monotone"
      dataKey={col}
      stackId={stackId}
      stroke={LINE_COLORS[ci % LINE_COLORS.length]}
      fill={`${LINE_COLORS[ci % LINE_COLORS.length]}40`}
      strokeWidth={2}
    />
  ));

  const seriesBars = cols.map((col, ci) => (
    <Bar
      key={col}
      dataKey={col}
      stackId={stackId}
      fill={LINE_COLORS[ci % LINE_COLORS.length]}
      radius={[2, 2, 0, 0]}
    />
  ));

  if (kind === "bar") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows}>
          {commonAxes}
          {seriesBars}
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (kind === "area") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows}>
          {commonAxes}
          {seriesAreas}
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={rows}>
        {commonAxes}
        {seriesLines}
      </LineChart>
    </ResponsiveContainer>
  );
}

class ChartErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean; error?: string }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: any) {
    return { hasError: true, error: String(error?.message || error) };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-3 text-xs text-amber-400 bg-amber-950/20 border border-amber-800/40 rounded-lg">
          ⚠️ Unable to render chart: {this.state.error}
        </div>
      );
    }
    return this.props.children;
  }
}

export function SessionCharts({ charts }: { charts: SessionChart[] }) {
  if (!charts || !Array.isArray(charts) || charts.length === 0) return null;
  return (
    <div className="mt-3 space-y-4 border-t border-[#262626] pt-3">
      {charts.map((chart, i) => {
        if (!chart || typeof chart !== "object") return null;
        const rows = parseChartRows(chart);
        const title = chart.title || chart.query || `Chart ${i + 1}`;
        const kind = (chart.chart_kind || chart.chartType || chart.kind || "line").toLowerCase();
        return (
          <ChartErrorBoundary key={i}>
            <div className="rounded-xl border border-[#262626] bg-[#141414] p-3 shadow-md">
              <p className="mb-2 text-xs font-semibold text-gray-300 flex items-center justify-between">
                <span>{title}</span>
                {kind !== "line" ? (
                  <span className="rounded bg-black/60 px-1.5 py-0.5 font-mono text-[10px] uppercase text-gray-400 border border-[#262626]">
                    {kind}
                  </span>
                ) : null}
              </p>
              <div className="h-56 w-full">
                {rows.length === 0 ? (
                  <div className="flex h-full items-center justify-center text-xs text-gray-500">
                    No data available for chart
                  </div>
                ) : (
                  <ChartBody chart={chart} rows={rows} />
                )}
              </div>
            </div>
          </ChartErrorBoundary>
        );
      })}
    </div>
  );
}
