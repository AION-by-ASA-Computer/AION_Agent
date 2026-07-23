"use client";

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
import type { SessionChart } from "@/lib/api/aion";

const LINE_VARS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5"] as const;

const tooltipStyle = {
  background: "hsl(var(--card))",
  border: "1px solid hsl(var(--border))",
  borderRadius: "var(--radius)",
  color: "hsl(var(--card-foreground))",
  fontSize: 11,
};

function seriesKeysForChart(chart: SessionChart, rows: Array<Record<string, unknown>>): string[] {
  if (!rows.length) return [];
  const xk = chart.x_key || "index";
  const all = Object.keys(rows[0]).filter((k) => k !== xk);
  const sk = chart.series_keys;
  if (sk?.length) {
    return sk.filter((k) => all.includes(k));
  }
  return all;
}

function ChartBody({ chart, rows }: { chart: SessionChart; rows: Array<Record<string, unknown>> }) {
  const xKey = chart.x_key || "index";
  const cols = seriesKeysForChart(chart, rows);
  const kind = chart.chart_kind || "line";
  const stacked = Boolean(chart.stacked);
  const stackId = stacked ? "stack" : undefined;
  const showLegend = !chart.legend_off;

  const commonAxes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border) / 0.65)" />
      <XAxis
        dataKey={xKey}
        stroke="hsl(var(--muted-foreground))"
        fontSize={10}
        tickLine={false}
        minTickGap={8}
      />
      <YAxis
        stroke="hsl(var(--muted-foreground))"
        fontSize={10}
        tickLine={false}
        width={chart.y_label ? 44 : 36}
        label={
          chart.y_label
            ? {
                value: chart.y_label,
                angle: -90,
                position: "insideLeft",
                fill: "hsl(var(--muted-foreground))",
                fontSize: 10,
              }
            : undefined
        }
      />
      <Tooltip contentStyle={tooltipStyle} />
      {showLegend ? (
        <Legend wrapperStyle={{ fontSize: 11, color: "hsl(var(--muted-foreground))" }} />
      ) : null}
    </>
  );

  const seriesLines = cols.map((col, ci) => (
    <Line
      key={col}
      type="monotone"
      dataKey={col}
      stroke={`hsl(var(${LINE_VARS[ci % LINE_VARS.length]}))`}
      dot={false}
      strokeWidth={2}
    />
  ));

  const seriesAreas = cols.map((col, ci) => (
    <Area
      key={col}
      type="monotone"
      dataKey={col}
      stackId={stackId}
      stroke={`hsl(var(${LINE_VARS[ci % LINE_VARS.length]}))`}
      fill={`hsl(var(${LINE_VARS[ci % LINE_VARS.length]}) / 0.35)`}
      strokeWidth={2}
    />
  ));

  const seriesBars = cols.map((col, ci) => (
    <Bar
      key={col}
      dataKey={col}
      stackId={stackId}
      fill={`hsl(var(${LINE_VARS[ci % LINE_VARS.length]}))`}
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

export function SessionCharts({ charts }: { charts: SessionChart[] }) {
  if (!charts.length) return null;
  return (
    <div className="mt-4 space-y-6 border-t border-border pt-4">
      {charts.map((chart, i) => {
        const rows = (chart.data || []) as Array<Record<string, unknown>>;
        const title = chart.query || `Chart ${i + 1}`;
        const kind = chart.chart_kind || "line";
        return (
          <div key={i} className="rounded-aion border border-border bg-muted/20 p-2">
            <p className="mb-2 text-xs text-muted-foreground">
              {title}
              {kind !== "line" ? (
                <span className="ml-2 rounded bg-muted px-1.5 py-0.5 font-mono text-[0.714em] uppercase text-muted-foreground">
                  {kind}
                </span>
              ) : null}
            </p>
            <div className="h-52 w-full">
              {rows.length === 0 ? (
                <div className="flex h-full items-center justify-center text-xs text-muted-foreground">Nessun dato</div>
              ) : (
                <ChartBody chart={chart} rows={rows} />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
