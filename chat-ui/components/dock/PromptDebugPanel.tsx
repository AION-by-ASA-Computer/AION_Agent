"use client";

import { useCallback, useMemo, useState, type ReactNode } from "react";
import { Copy, Check, Search } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

export type PromptInjectLayer = {
  key: string;
  text: string;
};

export type PromptMessageRow = {
  index: number;
  role: string;
  content: string;
  chars: number;
};

export type PromptToolRow = {
  name: string;
  description?: string;
  spec?: unknown;
};

export type PromptSnapshot = {
  phase?: string;
  system_prompt: string;
  tools: PromptToolRow[];
  messages: PromptMessageRow[];
  inject_layers: PromptInjectLayer[];
  stats: Record<string, number>;
  generation_kwargs?: Record<string, unknown>;
  turn_meta?: Record<string, unknown>;
  raw_concatenated: string;
  assistant_output?: string;
  plan_coerced_markdown?: string | null;
  plan_intercepts?: number;
  turn_metrics?: {
    artifact_parse_hits?: number;
    artifact_salvage?: number;
    raw_token_fallback_chunks?: number;
  };
  assistant_message_id?: string;
  stored_at_ms?: number;
};

type ViewTab = "raw" | "system" | "messages" | "injects" | "tools" | "output";

function formatTs(ms?: number): string {
  if (!ms) return "—";
  try {
    return new Date(ms).toLocaleString();
  } catch {
    return String(ms);
  }
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  }, [text]);

  return (
    <button
      type="button"
      onClick={() => void onCopy()}
      className="focus-ring inline-flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
      title={label}
    >
      {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
      {copied ? "OK" : label}
    </button>
  );
}

function RawBlock({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <pre
      className={cn(
        "whitespace-pre-wrap break-words rounded-lg border border-border/60 bg-muted/20 p-3 font-mono text-[11px] leading-relaxed text-foreground",
        className
      )}
    >
      {children ?? "—"}
    </pre>
  );
}

function highlightQuery(text: string, query: string): ReactNode {
  const q = query.trim();
  if (!q) return text;
  const lower = text.toLowerCase();
  const needle = q.toLowerCase();
  const parts: React.ReactNode[] = [];
  let start = 0;
  let idx = lower.indexOf(needle, start);
  while (idx !== -1) {
    if (idx > start) parts.push(text.slice(start, idx));
    parts.push(
      <mark key={idx} className="rounded bg-amber-200/80 px-0.5 text-foreground dark:bg-amber-500/30">
        {text.slice(idx, idx + needle.length)}
      </mark>
    );
    start = idx + needle.length;
    idx = lower.indexOf(needle, start);
  }
  if (start < text.length) parts.push(text.slice(start));
  return parts;
}

export function PromptDebugPanel({
  snapshots,
  enabled,
}: {
  snapshots: PromptSnapshot[];
  enabled: boolean;
}) {
  const t = useT();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [viewTab, setViewTab] = useState<ViewTab>("raw");
  const [search, setSearch] = useState("");

  const ordered = useMemo(
    () => [...snapshots].sort((a, b) => (b.stored_at_ms || 0) - (a.stored_at_ms || 0)),
    [snapshots]
  );

  const active =
    ordered.find((s) => s.assistant_message_id === selectedId) || ordered[0] || null;

  const viewTabs: { id: ViewTab; label: string }[] = [
    { id: "raw", label: t("prompt_debug.tab.raw") },
    { id: "output", label: t("prompt_debug.tab.output") },
    { id: "system", label: t("prompt_debug.tab.system") },
    { id: "messages", label: t("prompt_debug.tab.messages") },
    { id: "injects", label: t("prompt_debug.tab.injects") },
    { id: "tools", label: t("prompt_debug.tab.tools") },
  ];

  if (!enabled) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        <p className="font-medium text-foreground">{t("prompt_debug.disabled_title")}</p>
        <p className="mt-2">{t("prompt_debug.disabled_hint")}</p>
      </div>
    );
  }

  if (!active) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        <p>{t("prompt_debug.empty")}</p>
      </div>
    );
  }

  const stats = active.stats || {};
  const meta = active.turn_meta || {};

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-3 border-b border-border p-3">
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-[11px] font-medium text-muted-foreground">
            {t("prompt_debug.turn_select")}
          </label>
          <select
            className="focus-ring min-w-[12rem] flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-xs"
            value={active.assistant_message_id || ""}
            onChange={(e) => setSelectedId(e.target.value || null)}
          >
            {ordered.map((snap, i) => (
              <option key={snap.assistant_message_id || `snap-${i}`} value={snap.assistant_message_id || ""}>
                {formatTs(snap.stored_at_ms)} · {snap.assistant_message_id?.slice(0, 8) || `#${i + 1}`}
              </option>
            ))}
          </select>
          <CopyButton text={active.raw_concatenated} label={t("prompt_debug.copy_all")} />
        </div>

        <div className="flex flex-wrap gap-2 text-[10px] text-muted-foreground">
          <span className="rounded bg-muted px-1.5 py-0.5">
            {t("prompt_debug.stats.total")}: {stats.total ?? "—"}
          </span>
          <span className="rounded bg-muted px-1.5 py-0.5">
            {t("prompt_debug.stats.messages")}: {stats.messages ?? "—"}
          </span>
          <span className="rounded bg-muted px-1.5 py-0.5">
            {t("prompt_debug.stats.overhead")}: {stats.overhead ?? "—"}
          </span>
          <span className="rounded bg-muted px-1.5 py-0.5">
            {t("prompt_debug.stats.count")}: {active.messages?.length ?? 0}
          </span>
          {meta.agent_mode ? (
            <span className="rounded bg-muted px-1.5 py-0.5">mode: {String(meta.agent_mode)}</span>
          ) : null}
          {meta.reasoning_effort ? (
            <span className="rounded bg-muted px-1.5 py-0.5">
              reasoning: {String(meta.reasoning_effort)}
            </span>
          ) : null}
          {typeof active.plan_intercepts === "number" ? (
            <span className="rounded bg-muted px-1.5 py-0.5">
              plan intercepts: {active.plan_intercepts}
            </span>
          ) : null}
          {active.phase ? (
            <span className="rounded bg-muted px-1.5 py-0.5">phase: {active.phase}</span>
          ) : null}
          {typeof active.turn_metrics?.artifact_parse_hits === "number" ? (
            <span className="rounded bg-muted px-1.5 py-0.5">
              artifact hits: {active.turn_metrics.artifact_parse_hits}
            </span>
          ) : null}
          {typeof active.turn_metrics?.artifact_salvage === "number" &&
          active.turn_metrics.artifact_salvage > 0 ? (
            <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-700 dark:text-amber-300">
              artifact salvage: {active.turn_metrics.artifact_salvage}
            </span>
          ) : null}
          {typeof active.turn_metrics?.raw_token_fallback_chunks === "number" ? (
            <span className="rounded bg-muted px-1.5 py-0.5">
              token fallback: {active.turn_metrics.raw_token_fallback_chunks}
            </span>
          ) : null}
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("prompt_debug.search_placeholder")}
            className="focus-ring w-full rounded-md border border-border bg-background py-1.5 pl-8 pr-2 text-xs"
          />
        </div>

        <div className="flex flex-wrap gap-1">
          {viewTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setViewTab(tab.id)}
              className={cn(
                "focus-ring rounded-md px-2 py-1 text-[11px] font-medium",
                viewTab === tab.id
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {viewTab === "raw" && (
          <RawBlock>{highlightQuery(active.raw_concatenated, search)}</RawBlock>
        )}

        {viewTab === "output" && (
          <div className="space-y-3">
            <div>
              <div className="mb-1 flex items-center justify-between text-[11px] font-medium text-muted-foreground">
                <span>{t("prompt_debug.output.model")}</span>
                <CopyButton
                  text={active.assistant_output || ""}
                  label={t("prompt_debug.copy_section")}
                />
              </div>
              {active.assistant_output ? (
                <RawBlock>{highlightQuery(active.assistant_output, search)}</RawBlock>
              ) : (
                <p className="text-xs text-muted-foreground">{t("prompt_debug.output.pending")}</p>
              )}
            </div>
            {active.plan_coerced_markdown ? (
              <div>
                <div className="mb-1 flex items-center justify-between text-[11px] font-medium text-muted-foreground">
                  <span>{t("prompt_debug.output.coerced")}</span>
                  <CopyButton
                    text={active.plan_coerced_markdown}
                    label={t("prompt_debug.copy_section")}
                  />
                </div>
                <RawBlock>{highlightQuery(active.plan_coerced_markdown, search)}</RawBlock>
              </div>
            ) : null}
          </div>
        )}

        {viewTab === "system" && (
          <div className="space-y-2">
            <CopyButton text={active.system_prompt} label={t("prompt_debug.copy_section")} />
            <RawBlock>{highlightQuery(active.system_prompt, search)}</RawBlock>
          </div>
        )}

        {viewTab === "messages" && (
          <div className="space-y-3">
            {(active.messages || []).map((row) => (
              <div key={row.index} className="rounded-lg border border-border/60 bg-card/40">
                <div className="flex items-center justify-between border-b border-border/40 px-3 py-1.5 text-[11px] font-medium">
                  <span>
                    {row.role.toUpperCase()} [{row.index}] · {row.chars} chars
                  </span>
                  <CopyButton text={row.content} label={t("prompt_debug.copy_section")} />
                </div>
                <pre className="whitespace-pre-wrap break-words p-3 font-mono text-[11px] leading-relaxed">
                  {highlightQuery(row.content, search)}
                </pre>
              </div>
            ))}
          </div>
        )}

        {viewTab === "injects" && (
          <div className="space-y-3">
            {(active.inject_layers || []).length === 0 ? (
              <p className="text-xs text-muted-foreground">{t("prompt_debug.no_injects")}</p>
            ) : (
              active.inject_layers.map((layer, i) => (
                <div key={`${layer.key}-${i}`} className="rounded-lg border border-border/60 bg-card/40">
                  <div className="flex items-center justify-between border-b border-border/40 px-3 py-1.5 text-[11px] font-medium">
                    <span className="font-mono text-primary">{layer.key}</span>
                    <CopyButton text={layer.text} label={t("prompt_debug.copy_section")} />
                  </div>
                  <pre className="whitespace-pre-wrap break-words p-3 font-mono text-[11px] leading-relaxed">
                    {highlightQuery(layer.text, search)}
                  </pre>
                </div>
              ))
            )}
          </div>
        )}

        {viewTab === "tools" && (
          <div className="space-y-3">
            {(active.tools || []).map((tool) => (
              <details key={tool.name} className="rounded-lg border border-border/60 bg-card/40">
                <summary className="cursor-pointer px-3 py-2 text-xs font-medium">
                  {tool.name}
                  {tool.description ? (
                    <span className="ml-2 font-normal text-muted-foreground">
                      — {tool.description.slice(0, 120)}
                      {tool.description.length > 120 ? "…" : ""}
                    </span>
                  ) : null}
                </summary>
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words border-t border-border/40 p-3 font-mono text-[10px] leading-relaxed text-muted-foreground">
                  {tool.spec ? JSON.stringify(tool.spec, null, 2) : "—"}
                </pre>
              </details>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
