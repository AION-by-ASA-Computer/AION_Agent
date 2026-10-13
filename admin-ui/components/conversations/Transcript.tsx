"use client";

import { useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Brain, ChevronRight, Download, FileText, Paperclip, ThumbsDown, ThumbsUp, Wrench } from "lucide-react";
import { apiBase } from "@/lib/api";
import { getStoredToken } from "@/lib/auth/storage";
import { cn } from "@/lib/cn";
import type { ThreadArtifact, ThreadMessage, ThreadStep } from "./types";
import { isFlagged } from "./types";
import { dayBucket, timeOnly, toMs } from "./format";
import { CodeArtifact, GeneratedFile, PiiReview, PiiReviewFile, artifactLanguage, parseContent } from "./chat/artifacts";

type T = (key: string, vars?: Record<string, string | number>) => string;
const k = "admin_conversations.detail";

/** Same markdown surface as chat-ui: `.prose-chat` rules plus bordered code blocks and scrollable tables. */
const mdComponents: Components = {
  a: (p) => <a target="_blank" rel="noreferrer" {...p} />,
  table: (p) => (
    <div className="table-wrapper">
      <table {...p} />
    </div>
  ),
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children, ...p }) => {
    const lang = /language-(\w+)/.exec(className || "")?.[1];
    if (!lang) return <code {...p}>{children}</code>;
    return (
      <div className="not-prose my-3 overflow-hidden rounded-xl border border-border/80 bg-[#0d1117] text-[12px] shadow-sm ring-1 ring-black/5 dark:ring-white/10">
        <div className="border-b border-white/10 bg-[#161b22] px-3.5 py-2 font-mono text-[0.86em] font-medium uppercase tracking-wide text-[#8b949e]">{lang}</div>
        <pre className="m-0 max-h-[min(32rem,55vh)] overflow-auto whitespace-pre-wrap break-words p-4 font-mono leading-[1.65] text-[#e6edf3]">
          <code>{String(children).replace(/\n$/, "")}</code>
        </pre>
      </div>
    );
  },
};

export function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-chat">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

const pre =
  "max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/50 px-3 py-2 font-mono text-xs leading-relaxed";

/** chat-ui's compact activity: one quiet line ("N tool calls"), reasoning and tool calls underneath on a rail. */
function Activity({ m, t }: { m: ThreadMessage; t: T }) {
  const steps = m.steps ?? [];
  const reasoning = m.reasoning?.trim() ?? "";
  const failed = steps.filter((s) => s.is_error).length;
  const [open, setOpen] = useState(failed > 0);
  const [thinkOpen, setThinkOpen] = useState(false);
  if (!steps.length && !reasoning) return null;
  return (
    <div className="mb-1 text-[13px] leading-5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={cn("focus-ring group inline-flex max-w-full items-center gap-1 rounded-md py-0.5 pr-1 text-left transition-colors", failed ? "text-destructive" : "text-muted-foreground hover:text-foreground")}
      >
        <span className="truncate">
          {steps.length ? t(`${k}.tool_calls`, { n: steps.length }) : t(`${k}.reasoning`)}
          {failed > 0 && ` · ${t(`${k}.tool_errors`, { n: failed })}`}
        </span>
        <ChevronRight size={14} className={cn("shrink-0 opacity-50 transition-transform duration-200 group-hover:opacity-80", open && "rotate-90")} aria-hidden />
      </button>
      {open && (
        <div className="ml-1.5 mt-1.5 space-y-2.5 border-l border-border/70 pl-4">
          {reasoning && (
            <div>
              <button type="button" onClick={() => setThinkOpen((v) => !v)} aria-expanded={thinkOpen} className="focus-ring inline-flex items-center gap-2 rounded-lg text-muted-foreground transition-colors hover:text-foreground">
                <Brain size={14} className="opacity-80" aria-hidden />
                <span className="text-xs font-medium">{t(`${k}.reasoning`)}</span>
                <ChevronRight size={13} className={cn("opacity-60 transition-transform duration-200", thinkOpen && "rotate-90")} aria-hidden />
              </button>
              {thinkOpen && <div className="mt-1.5 whitespace-pre-wrap rounded-lg bg-muted/35 px-3 py-2.5 text-[0.929em] leading-relaxed text-muted-foreground">{reasoning}</div>}
            </div>
          )}
          {steps.map((s) => (
            <div key={s.id} className="rounded-xl border border-border/60 bg-muted/30">
              <StepRow step={s} t={t} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StepRow({ step: s, t }: { step: ThreadStep; t: T }) {
  const [open, setOpen] = useState(!!s.is_error);
  const hasBody = !!(s.input || s.output);
  return (
    <div>
      <button
        type="button"
        disabled={!hasBody}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={hasBody ? open : undefined}
        className="focus-ring flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left disabled:cursor-default"
      >
        <span className={cn("h-2 w-2 shrink-0 rounded-full", s.is_error ? "bg-destructive" : "bg-success")} aria-hidden />
        <span className="min-w-0 flex-1 truncate font-mono text-[13px]">{s.name}</span>
        <span className={cn("shrink-0 text-xs", s.is_error ? "font-medium text-destructive" : "text-muted-foreground")}>
          {s.is_error ? t(`${k}.failed`) : t(`${k}.ok`)}
        </span>
        {hasBody && <ChevronRight className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} aria-hidden />}
      </button>
      {open && hasBody && (
        <div className="flex flex-col gap-2 px-3 pb-3">
          {s.input && (
            <div>
              <div className="mb-1 text-xs text-muted-foreground">{t(`${k}.input`)}</div>
              <pre className={pre}>{s.input}</pre>
            </div>
          )}
          {s.output && (
            <div>
              <div className="mb-1 text-xs text-muted-foreground">{t(`${k}.output`)}</div>
              <pre className={cn(pre, s.is_error && "text-destructive")}>{s.output}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function downloadUrl(convId: string, a: ThreadArtifact) {
  if (!a.storage_key) return undefined;
  const token = getStoredToken();
  return `${apiBase()}/sessions/${encodeURIComponent(convId)}/download?relative_path=${encodeURIComponent(a.storage_key)}${
    token ? `&access_token=${encodeURIComponent(token)}` : ""
  }`;
}

const isPlan = (a: ThreadArtifact) => a.kind === "plan" || (a.original_name || "").toLowerCase().includes("execution_plan");

function Artifacts({ items, convId, t }: { items: ThreadArtifact[]; convId: string; t: T }) {
  const [planOpen, setPlanOpen] = useState(false);
  const plans = items.filter(isPlan);
  const files = items.filter((a) => !isPlan(a));
  return (
    <div className="flex flex-col gap-2">
      {plans.map((p) => {
        const url = downloadUrl(convId, p);
        return (
          <div key={p.id} className="rounded-xl border border-border/70 bg-card">
            <div className="flex items-center gap-2 px-3 py-2">
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <button
                type="button"
                onClick={() => setPlanOpen((v) => !v)}
                aria-expanded={planOpen}
                className="focus-ring min-w-0 flex-1 truncate rounded-md text-left text-sm font-medium"
              >
                {t(`${k}.plan`)}
              </button>
              {url && (
                <a href={url} target="_blank" rel="noopener noreferrer" aria-label={t(`${k}.download`)} className="focus-ring rounded-lg p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
                  <Download className="h-3.5 w-3.5" aria-hidden />
                </a>
              )}
            </div>
            {planOpen && <pre className={cn(pre, "mx-3 mb-3 max-h-72")}>{p.content || p.original_name || p.storage_key}</pre>}
          </div>
        );
      })}
      {files.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label={t(`${k}.attachments`)}>
          {files.map((a) => {
            const url = downloadUrl(convId, a);
            const name = a.original_name || a.storage_key || a.id;
            const inner = (
              <>
                <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                <span className="max-w-[16rem] truncate">{name}</span>
                {a.size_bytes ? <span className="text-xs tabular-nums text-muted-foreground">{Math.max(1, Math.round(a.size_bytes / 1024))} KB</span> : null}
              </>
            );
            return (
              <li key={a.id}>
                {url ? (
                  <a href={url} target="_blank" rel="noopener noreferrer" title={t(`${k}.download`)} className="focus-ring inline-flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-1.5 text-sm transition-colors hover:bg-secondary">
                    {inner}
                  </a>
                ) : (
                  <span className="inline-flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-1.5 text-sm">{inner}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ToolMessage({ m }: { m: ThreadMessage }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="focus-ring inline-flex max-w-full items-center gap-2 rounded-xl border border-border/70 bg-card px-3 py-1.5 text-left text-xs transition-colors hover:bg-secondary"
      >
        <Wrench className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span className="truncate font-mono text-[13px]">{m.tool_name}</span>
        <ChevronRight className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} aria-hidden />
      </button>
      {open && <pre className={cn(pre, "mt-1.5")}>{m.content}</pre>}
    </div>
  );
}

function Rating({ m, t }: { m: ThreadMessage; t: T }) {
  if (m.rating === 1)
    return (
      <span className="inline-flex items-center gap-1 font-medium text-success">
        <ThumbsUp className="h-3.5 w-3.5" aria-hidden />
        {t(`${k}.liked`)}
      </span>
    );
  if (m.rating === -1)
    return (
      <span className="inline-flex items-center gap-1 font-medium text-destructive">
        <ThumbsDown className="h-3.5 w-3.5" aria-hidden />
        {t(`${k}.disliked`)}
      </span>
    );
  return null;
}

/** The agent's answer: prose, inline `<aion_artifact>` blocks and stored attachments, each drawn like chat-ui. */
function AssistantBody({ m, convId, t }: { m: ThreadMessage; convId: string; t: T }) {
  const parts = parseContent(m.content ?? "");
  const inline = new Set(parts.flatMap((p) => (p.kind === "artifact" ? [p.identifier, p.title, p.type].filter(Boolean) : [])));
  const stored = (m.artifacts ?? []).filter((a) => {
    if (isPlan(a)) return false;
    const name = a.original_name || "";
    return !(name && inline.has(name));
  });
  return (
    <>
      {parts.map((p, i) =>
        p.kind === "text" ? (
          <Markdown key={i} text={p.text.trim()} />
        ) : p.type === "pii_review" ? (
          <PiiReview key={i} content={p.body} t={t} />
        ) : (
          <CodeArtifact key={i} title={p.title || p.identifier || p.type} language={artifactLanguage(p.type)} code={p.body} defaultOpen t={t} />
        ),
      )}
      {stored.map((a) => {
        const url = downloadUrl(convId, a);
        if ((a.mime || a.original_name) === "pii_review") return <PiiReviewFile key={a.id} url={url} t={t} />;
        if (a.kind === "artifact" && /\.(txt|md|py|js|ts|tsx|jsx|json|html|css|ya?ml|sh)$/i.test(a.storage_key || ""))
          return <CodeArtifact key={a.id} title={a.original_name || a.id} language={artifactLanguage(a.mime || "", a.storage_key ?? "")} path={a.storage_key ?? undefined} downloadUrl={url} t={t} />;
        return (
          <div key={a.id} className="max-w-xl">
            <GeneratedFile name={a.original_name || a.storage_key || a.id} size={a.size_bytes ?? undefined} downloadUrl={url} t={t} />
          </div>
        );
      })}
    </>
  );
}

/** The thread exactly as chat-ui draws it: user bubble on the right, the agent's turn plain on the left. */
export function Transcript({
  messages,
  convId,
  highlightId,
  showTools,
  t,
}: {
  messages: ThreadMessage[];
  convId: string;
  highlightId: string | null;
  showTools: boolean;
  t: T;
}) {
  const rows = messages.filter((m) => showTools || !m.tool_name);
  const days = rows.map((m) => {
    const ms = toMs(m.created_at);
    return ms ? dayBucket(ms, t) : null;
  });

  return (
    <ol className="chat-font mx-auto flex w-full max-w-3xl flex-col text-[14px] text-foreground">
      {rows.map((m, i) => {
        const ms = toMs(m.created_at);
        const day = days[i];
        const showDay = !!day && day.key !== (days.slice(0, i).reverse().find(Boolean)?.key ?? "");
        const isUser = m.role === "user";
        const isTool = !!m.tool_name;
        const flagged = isFlagged(m);
        const hl = m.id === highlightId;
        const prev = i > 0 ? rows[i - 1] : null;
        const gap = i === 0 ? "" : !isUser && prev?.role === "user" ? "mt-0.5" : isUser && prev && prev.role !== "user" ? "mt-6" : "mt-4";
        const afterUser = !isUser && prev?.role === "user";
        const meta = (
          <div className={cn("flex flex-wrap items-center gap-x-2 gap-y-0.5 px-1 text-[11px] text-muted-foreground/80", isUser && "justify-end")}>
            {isTool && <span className="font-medium text-muted-foreground">{t(`${k}.tool`)}</span>}
            {timeOnly(ms) && <span className="tabular-nums">{timeOnly(ms)}</span>}
            <span className="tabular-nums">#{m.seq}</span>
            <Rating m={m} t={t} />
          </div>
        );
        return (
          <li key={m.id} className={gap}>
            {showDay && (
              <div className="my-6 flex items-center gap-3 text-xs font-medium text-muted-foreground" role="separator">
                <span className="h-px flex-1 bg-border/60" />
                {day!.label}
                <span className="h-px flex-1 bg-border/60" />
              </div>
            )}
            <div id={`message-${m.id}`} data-flagged={flagged ? "true" : undefined} className="scroll-mt-28">
              {isUser ? (
                <div className="flex flex-col items-end gap-1">
                  {m.artifacts && m.artifacts.length > 0 && (
                    <div className="max-w-[min(92%,42rem)]">
                      <Artifacts items={m.artifacts} convId={convId} t={t} />
                    </div>
                  )}
                  <div
                    className={cn(
                      "max-w-[min(92%,42rem)] rounded-3xl border border-border/60 bg-muted/60 px-4 py-3 shadow-2xs sm:max-w-[min(70%,42rem)] dark:border-border dark:bg-muted/80",
                      hl && "ring-2 ring-warning/60",
                    )}
                  >
                    <Markdown text={m.content?.trim() || ""} />
                  </div>
                  {meta}
                </div>
              ) : (
                <div
                  className={cn(
                    "mr-auto flex max-w-[min(100%,48rem)] flex-col gap-2 rounded-2xl px-5 transition-colors duration-700",
                    afterUser ? "pb-2 pt-0.5" : "py-3",
                    hl ? "bg-warning/10" : flagged && "bg-destructive/[0.06]",
                  )}
                >
                  <Activity m={m} t={t} />
                  {isTool ? <ToolMessage m={m} /> : <AssistantBody m={m} convId={convId} t={t} />}
                  {m.feedback_comment && (
                    <p className="rounded-xl border border-border/60 bg-muted/40 px-3 py-2 text-sm">
                      <span className="mr-1.5 text-xs font-medium text-muted-foreground">{t(`${k}.comment`)}</span>
                      {m.feedback_comment}
                    </p>
                  )}
                  {meta}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
