"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronRight, Download, FileText, Paperclip, ThumbsDown, ThumbsUp, Wrench } from "lucide-react";
import { apiBase } from "@/lib/api";
import { getStoredToken } from "@/lib/auth/storage";
import { cn } from "@/lib/cn";
import { md } from "@/components/skills/SkillPreview";
import type { ThreadArtifact, ThreadMessage, ThreadStep } from "./types";
import { isFlagged } from "./types";
import { timeOnly, toMs } from "./format";

type T = (key: string, vars?: Record<string, string | number>) => string;
const k = "admin_conversations.detail";

function Markdown({ text }: { text: string }) {
  return (
    <div className="text-sm leading-relaxed [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={md}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

function Disclosure({
  open,
  onToggle,
  label,
  tone,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  label: React.ReactNode;
  tone?: "error";
  children: React.ReactNode;
}) {
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className={cn(
          "focus-ring -ml-2 inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium transition-colors hover:bg-secondary",
          tone === "error" ? "text-destructive" : "text-muted-foreground hover:text-foreground",
        )}
      >
        <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-90")} aria-hidden />
        {label}
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  );
}

const pre =
  "max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-secondary px-3 py-2 font-mono text-xs leading-relaxed";

function Steps({ steps, t }: { steps: ThreadStep[]; t: T }) {
  const failed = steps.filter((s) => s.is_error).length;
  const [open, setOpen] = useState(failed > 0);
  return (
    <Disclosure
      open={open}
      onToggle={() => setOpen((v) => !v)}
      tone={failed ? "error" : undefined}
      label={
        <>
          <Wrench className="h-3.5 w-3.5" aria-hidden />
          {t(`${k}.tool_calls`, { n: steps.length })}
          {failed > 0 && <span>· {t(`${k}.tool_errors`, { n: failed })}</span>}
        </>
      }
    >
      <ol className="flex flex-col gap-1.5">
        {steps.map((s) => (
          <li key={s.id} className="rounded-xl border border-border/70 bg-card">
            <StepRow step={s} t={t} />
          </li>
        ))}
      </ol>
    </Disclosure>
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
  const [reasoningOpen, setReasoningOpen] = useState<Record<string, boolean>>({});
  const rows = messages.filter((m) => showTools || !m.tool_name);

  return (
    <ol className="flex flex-col gap-6">
      {rows.map((m) => {
        const isUser = m.role === "user";
        const isTool = !!m.tool_name;
        const flagged = isFlagged(m);
        const when = timeOnly(toMs(m.created_at));
        const hl = m.id === highlightId;
        return (
          <li
            key={m.id}
            id={`message-${m.id}`}
            data-flagged={flagged ? "true" : undefined}
            className={cn(
              "scroll-mt-24 flex flex-col gap-2 rounded-2xl transition-colors duration-700",
              (hl || flagged) && "-mx-3 px-3 py-3",
              hl ? "bg-warning/10" : flagged && "bg-destructive/[0.06]",
            )}
          >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span className={cn("font-semibold", !isUser && !isTool && "text-foreground")}>
                {isTool ? `${t(`${k}.tool`)} · ${m.tool_name}` : isUser ? t(`${k}.human`) : t(`${k}.agent`)}
              </span>
              <span className="tabular-nums">#{m.seq}</span>
              {when && <span className="tabular-nums">{when}</span>}
              {m.rating === 1 && (
                <span className="inline-flex items-center gap-1 font-medium text-success">
                  <ThumbsUp className="h-3.5 w-3.5" aria-hidden />
                  {t(`${k}.liked`)}
                </span>
              )}
              {m.rating === -1 && (
                <span className="inline-flex items-center gap-1 font-medium text-destructive">
                  <ThumbsDown className="h-3.5 w-3.5" aria-hidden />
                  {t(`${k}.disliked`)}
                </span>
              )}
            </div>

            {isTool ? (
              <ToolMessage m={m} />
            ) : isUser ? (
              <div className="max-w-[46rem] rounded-2xl bg-secondary px-4 py-3">
                <Markdown text={m.content?.trim() || ""} />
              </div>
            ) : (
              <div className="max-w-[46rem]">
                <Markdown text={m.content?.trim() || ""} />
              </div>
            )}

            {m.feedback_comment && (
              <p className="max-w-[46rem] rounded-xl bg-secondary/70 px-3 py-2 text-sm">
                <span className="mr-1.5 text-xs font-medium text-muted-foreground">{t(`${k}.comment`)}</span>
                {m.feedback_comment}
              </p>
            )}

            {m.reasoning?.trim() && (
              <Disclosure
                open={!!reasoningOpen[m.id]}
                onToggle={() => setReasoningOpen((s) => ({ ...s, [m.id]: !s[m.id] }))}
                label={t(`${k}.reasoning`)}
              >
                <pre className={cn(pre, "max-w-[46rem]")}>{m.reasoning}</pre>
              </Disclosure>
            )}

            {m.steps && m.steps.length > 0 && <Steps steps={m.steps} t={t} />}
            {m.artifacts && m.artifacts.length > 0 && <Artifacts items={m.artifacts} convId={convId} t={t} />}
          </li>
        );
      })}
    </ol>
  );
}
