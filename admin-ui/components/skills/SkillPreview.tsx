"use client";

import { useEffect, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Loader2 } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { Dialog } from "@/components/profiles/Dialog";

type T = (key: string, vars?: Record<string, string | number>) => string;

const md: Components = {
  h1: (p) => <h1 className="mb-3 mt-6 text-lg font-semibold tracking-[-0.015em] first:mt-0" {...p} />,
  h2: (p) => <h2 className="mb-2 mt-6 text-base font-semibold first:mt-0" {...p} />,
  h3: (p) => <h3 className="mb-2 mt-5 text-sm font-semibold first:mt-0" {...p} />,
  p: (p) => <p className="my-3 leading-relaxed" {...p} />,
  ul: (p) => <ul className="my-3 list-disc space-y-1 pl-5" {...p} />,
  ol: (p) => <ol className="my-3 list-decimal space-y-1 pl-5" {...p} />,
  a: (p) => <a className="underline underline-offset-4" target="_blank" rel="noreferrer" {...p} />,
  hr: () => <hr className="my-5 border-border/60" />,
  blockquote: (p) => <blockquote className="my-3 rounded-xl bg-secondary/60 px-4 py-2 text-muted-foreground" {...p} />,
  pre: (p) => <pre className="my-3 overflow-x-auto rounded-xl bg-secondary px-4 py-3 font-mono text-[12.5px] leading-relaxed" {...p} />,
  code: ({ className, ...p }) => (
    <code className={className ?? "rounded-md bg-secondary px-1.5 py-0.5 font-mono text-[12.5px]"} {...p} />
  ),
  table: (p) => (
    <div className="my-3 overflow-x-auto rounded-xl border border-border/70">
      <table className="w-full text-left text-[13px]" {...p} />
    </div>
  ),
  th: (p) => <th className="border-b border-border/70 bg-secondary/60 px-3 py-2 font-medium" {...p} />,
  td: (p) => <td className="border-b border-border/40 px-3 py-2 align-top" {...p} />,
};

/** Read-only look at a skill's protocol, so it can be judged before attaching it to a profile. */
export function SkillPreview({ name, t, onClose }: { name: string; t: T; onClose: () => void }) {
  const [state, setState] = useState<{ content: string; description: string; tags: string[] } | "error" | null>(null);

  useEffect(() => {
    let live = true;
    apiFetch(`${apiBase()}/admin/skills/${encodeURIComponent(name)}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(String(res.status));
        const d = await res.json();
        if (live)
          setState({ content: d.content || "", description: d.metadata?.description || "", tags: d.metadata?.tags || [] });
      })
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
  }, [name]);

  return (
    <Dialog title={name} closeLabel={t("admin_profiles.skills.preview_close")} onClose={onClose} className="max-w-2xl">
      {state === null ? (
        <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t("admin_profiles.skills.preview_loading")}
        </div>
      ) : state === "error" ? (
        <p className="py-10 text-sm text-destructive" role="alert">
          {t("admin_profiles.skills.preview_error")}
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {(state.description || state.tags.length > 0) && (
            <div className="flex flex-col gap-2">
              {state.description && <p className="text-sm text-muted-foreground">{state.description}</p>}
              {state.tags.length > 0 && (
                <ul className="flex flex-wrap gap-1.5">
                  {state.tags.map((tag) => (
                    <li key={tag} className="rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground">
                      {tag}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <div className="max-h-[58vh] overflow-y-auto rounded-2xl border border-border/70 bg-background px-5 py-4 text-sm">
            {state.content.trim() ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={md}>
                {state.content}
              </ReactMarkdown>
            ) : (
              <p className="text-muted-foreground">{t("admin_profiles.skills.preview_empty")}</p>
            )}
          </div>
        </div>
      )}
    </Dialog>
  );
}
