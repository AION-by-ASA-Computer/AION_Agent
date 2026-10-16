"use client";

import { useEffect, useMemo, useState } from "react";
import { Archive, Check, Copy, Download, ExternalLink, File as FileIcon, FileSpreadsheet, FileText, Image as ImageIcon, Loader2, Presentation, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/cn";

type T = (key: string, vars?: Record<string, string | number>) => string;
const k = "admin_conversations.detail";

export type ContentPart =
  | { kind: "text"; text: string }
  | { kind: "artifact"; type: string; title: string; identifier: string; body: string };

const ARTIFACT_RE = /<aion_artifact\b([^>]*)>([\s\S]*?)(?:<\/aion_artifact>|$)/g;
const attr = (src: string, name: string) => new RegExp(`${name}="([^"]*)"`).exec(src)?.[1] ?? "";

/** Splits persisted assistant text into prose and `<aion_artifact>` blocks, as chat-ui does while streaming. */
export function parseContent(content: string): ContentPart[] {
  const parts: ContentPart[] = [];
  let last = 0;
  for (const m of content.matchAll(ARTIFACT_RE)) {
    const at = m.index ?? 0;
    if (at > last) parts.push({ kind: "text", text: content.slice(last, at) });
    parts.push({
      kind: "artifact",
      type: attr(m[1], "type"),
      title: attr(m[1], "title"),
      identifier: attr(m[1], "identifier"),
      body: m[2].replace(/^\n/, "").replace(/\n$/, ""),
    });
    last = at + m[0].length;
  }
  if (last < content.length) parts.push({ kind: "text", text: content.slice(last) });
  return parts.filter((p) => p.kind === "artifact" || p.text.trim());
}

const LANG: Record<string, string> = { py: "python", js: "javascript", ts: "typescript", md: "markdown", yml: "yaml", sh: "bash" };
export function artifactLanguage(type: string, path = ""): string {
  const ext = path.toLowerCase().split(".").pop() || "";
  if (LANG[ext]) return LANG[ext];
  if (["tsx", "jsx", "json", "html", "css", "yaml", "python", "javascript", "typescript"].includes(ext)) return ext;
  const t = type.trim().toLowerCase();
  return t === "plan" ? "markdown" : LANG[t] || t || "text";
}

/** Fetches a stored artifact's text when the thread only carries its path. */
export function useFileText(url: string | undefined, enabled: boolean) {
  const [state, setState] = useState<{ url: string; text?: string; error?: boolean } | null>(null);
  useEffect(() => {
    if (!url || !enabled) return;
    let live = true;
    fetch(url)
      .then((r) => (r.ok ? r.text() : Promise.reject(r)))
      .then((text) => live && setState({ url, text }))
      .catch(() => live && setState({ url, error: true }));
    return () => {
      live = false;
    };
  }, [url, enabled]);
  const cur = state && state.url === url ? state : null;
  return { text: cur?.text, error: !!cur?.error, loading: !!url && enabled && !cur };
}

/** Same dark, collapsible code artifact chat-ui draws (no syntax colouring). */
export function CodeArtifact({
  title,
  language,
  code,
  path,
  downloadUrl,
  defaultOpen,
  t,
}: {
  title: string;
  language: string;
  code?: string;
  path?: string;
  downloadUrl?: string;
  defaultOpen?: boolean;
  t: T;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  const [copied, setCopied] = useState(false);
  const needsFetch = !code?.trim() && !!downloadUrl;
  const file = useFileText(downloadUrl, open && needsFetch);
  const body = code?.trim() ? code : file.text ?? "";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(body);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard unavailable */
    }
  };
  const btn = "focus-ring inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-[0.786em] text-[#c9d1d9] transition-colors hover:bg-white/10";

  return (
    <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)} className="overflow-hidden rounded-xl border border-border bg-[#0d1117] text-xs shadow-sm ring-1 ring-white/5">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 border-b border-white/10 bg-[#161b22] px-3.5 py-2 text-[#c9d1d9]">
        <div className="min-w-0">
          <div className="truncate text-[0.857em] font-semibold text-[#f0f6fc]">{title}</div>
          <div className="mt-0.5 truncate font-mono text-[0.714em] text-[#8b949e]">{path || language}</div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {downloadUrl && (
            <a className={btn} href={downloadUrl} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
              <Download size={12} aria-hidden />
              {t(`${k}.download`)}
            </a>
          )}
          {body && (
            <button
              type="button"
              className={btn}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                void copy();
              }}
            >
              {copied ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />}
              {copied ? t(`${k}.code_copied`) : t(`${k}.code_copy`)}
            </button>
          )}
        </div>
      </summary>
      <div className="max-h-[520px] overflow-auto">
        {file.loading ? (
          <div className="flex items-center gap-2 p-4 font-mono text-[0.857em] text-[#8b949e]">
            <Loader2 className="shrink-0 animate-spin" size={14} aria-hidden />
            {t(`${k}.artifact_loading`)}
          </div>
        ) : file.error ? (
          <p className="p-4 font-mono text-[0.857em] text-rose-300">{t(`${k}.artifact_error`)}</p>
        ) : (
          <pre className="m-0 whitespace-pre-wrap break-words p-4 font-mono text-[0.857em] leading-relaxed text-[#c9d1d9]">{body || t(`${k}.artifact_empty`)}</pre>
        )}
      </div>
    </details>
  );
}

interface PiiData {
  original_prompt?: string;
  censored_prompt?: string;
}

const cleanPrompt = (text?: string) =>
  (text || "")
    .replace(/\[session_memory\][\s\S]*?(?=--- runtime context|\[System instruction|$)/i, "")
    .replace(/--- runtime context[\s\S]*?--- end runtime context ---\n?/g, "")
    .replace(/\[System instruction[\s\S]*?(?=\n\n|$)/g, "")
    .replace(/Only after loading any required missing skills, proceed to execute the task\.\n*/g, "")
    .trim();

/** The PII review card, read-only: admins see what the user was asked to confirm. */
export function PiiReview({ content, t }: { content: string; t: T }) {
  let data: PiiData = {};
  try {
    data = JSON.parse(content || "{}");
  } catch {
    /* malformed or empty */
  }
  const prompt = cleanPrompt(data.censored_prompt);
  return (
    <div className="my-3 overflow-hidden rounded-xl border border-rose-500/30 bg-rose-500/5 shadow-sm">
      <div className="flex items-center gap-2 border-b border-rose-500/20 bg-rose-500/10 px-4 py-2">
        <ShieldAlert className="h-4 w-4 text-rose-600 dark:text-rose-400" aria-hidden />
        <h3 className="text-sm font-semibold text-rose-800 dark:text-rose-300">{t(`${k}.pii_title`)}</h3>
      </div>
      <p className="whitespace-pre-wrap p-4 text-sm font-medium text-foreground">{prompt || t(`${k}.pii_waiting`)}</p>
    </div>
  );
}

/** PII review stored only as an attachment: load the file, then draw the card. */
export function PiiReviewFile({ url, t }: { url?: string; t: T }) {
  const file = useFileText(url, true);
  if (file.loading) return <Loader2 className="my-3 h-4 w-4 animate-spin text-muted-foreground" aria-hidden />;
  return <PiiReview content={file.text ?? ""} t={t} />;
}

type Tone = { icon: typeof FileText; badge: string; card: string; iconColor: string };
const tones: Record<string, Tone> = {
  blue: { icon: FileText, badge: "bg-blue-500/15 border-blue-500/30", card: "bg-blue-500/[0.08] border-blue-500/30 hover:border-blue-500/50", iconColor: "text-blue-600 dark:text-blue-400" },
  green: { icon: FileSpreadsheet, badge: "bg-emerald-500/15 border-emerald-500/30", card: "bg-emerald-500/[0.08] border-emerald-500/30 hover:border-emerald-500/50", iconColor: "text-emerald-600 dark:text-emerald-400" },
  orange: { icon: Presentation, badge: "bg-orange-500/15 border-orange-500/30", card: "bg-orange-500/[0.08] border-orange-500/30 hover:border-orange-500/50", iconColor: "text-orange-600 dark:text-orange-400" },
  red: { icon: FileText, badge: "bg-red-500/15 border-red-500/30", card: "bg-red-500/[0.08] border-red-500/30 hover:border-red-500/50", iconColor: "text-red-600 dark:text-red-400" },
  violet: { icon: ImageIcon, badge: "bg-violet-500/15 border-violet-500/30", card: "bg-violet-500/[0.08] border-violet-500/30 hover:border-violet-500/50", iconColor: "text-violet-600 dark:text-violet-400" },
  amber: { icon: Archive, badge: "bg-amber-500/15 border-amber-500/30", card: "bg-amber-500/[0.08] border-amber-500/30 hover:border-amber-500/50", iconColor: "text-amber-600 dark:text-amber-400" },
  gray: { icon: FileIcon, badge: "bg-muted border-border", card: "bg-muted/40 border-border hover:border-foreground/25", iconColor: "text-muted-foreground" },
};
const toneFor = (ext: string) =>
  ["doc", "docx", "odt", "rtf"].includes(ext) ? tones.blue
  : ["xls", "xlsx", "csv", "tsv", "ods"].includes(ext) ? tones.green
  : ["ppt", "pptx", "odp"].includes(ext) ? tones.orange
  : ext === "pdf" ? tones.red
  : ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext) ? tones.violet
  : ["zip", "tar", "gz", "rar", "7z"].includes(ext) ? tones.amber
  : tones.gray;

/** Download card for a file the agent produced. */
export function GeneratedFile({ name, size, downloadUrl, t }: { name: string; size?: number; downloadUrl?: string; t: T }) {
  const clean = name.split("/").pop() || name;
  const ext = useMemo(() => (clean.includes(".") ? clean.split(".").pop()!.toLowerCase() : ""), [clean]);
  const tone = toneFor(ext);
  const Icon = tone.icon;
  const preview = ext === "pdf" || ext === "html" || tone === tones.violet;
  const inner = (
    <>
      <div className="flex min-w-0 flex-1 items-center gap-3.5">
        <div className={cn("flex size-11 shrink-0 items-center justify-center rounded-xl border", tone.badge)} aria-hidden>
          <Icon className={cn("size-5", tone.iconColor)} />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold leading-snug tracking-tight" title={clean}>{clean}</p>
          <p className="mt-0.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            {ext || "file"}
            {size ? ` · ${Math.max(1, Math.round(size / 1024))} KB` : ""}
          </p>
        </div>
      </div>
      {downloadUrl && (
        <span className="pointer-events-none inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-border bg-background/90 px-3.5 py-1.5 text-xs font-semibold shadow-2xs">
          {preview ? <ExternalLink size={13} aria-hidden /> : <Download size={13} aria-hidden />}
          {preview ? t(`${k}.open`) : t(`${k}.download`)}
        </span>
      )}
    </>
  );
  const cls = cn("flex items-center justify-between gap-3.5 rounded-2xl border p-3.5 shadow-2xs transition-colors", tone.card);
  return downloadUrl ? (
    <a href={downloadUrl} target="_blank" rel="noopener noreferrer" className={cn(cls, "focus-ring")}>
      {inner}
    </a>
  ) : (
    <div className={cls}>{inner}</div>
  );
}
