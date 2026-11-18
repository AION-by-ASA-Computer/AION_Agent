"use client";

/**
 * Step-by-step guide for developers preparing a custom MCP server for AION
 * (MCP Hub -> Upload MCP -> Guide). Same layout as the WhatsApp guide, without
 * screenshots: numbered steps, short explanations and copyable snippets.
 *
 * The snippets (aion-mcp.yaml template and a minimal server.py) come from the
 * backend (`GET /admin/mcp-custom/guide-template`, src/mcp_custom/template.py), the
 * single source of truth validated by the backend tests. The manifest can be
 * downloaded as `aion-mcp.yaml`, ready to put next to `server.py`.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Copy, Download, Loader2, TriangleAlert } from "lucide-react";
import { Dialog } from "@/components/profiles/Dialog";
import { Step, rich } from "@/components/sso/MicrosoftSsoGuide";
import { outlineBtn } from "@/components/ui/classes";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { HighlightedCode, type CodeLanguage } from "@/components/hub/HighlightedCode";

const k = "admin_hub.custom_guide";

type GuideTemplates = { aion_mcp_yaml: string; server_py: string };

/** Hand a text to the browser as a downloaded file (no server round trip). */
function downloadText(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/yaml;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Code snippet with a file-name header, syntax colours, a copy button and an optional download button. */
function CodeBlock({
  label,
  code,
  language,
  download,
}: {
  label: string;
  code: string;
  language: CodeLanguage;
  download?: { filename: string; label: string };
}) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-border">
      <div className="flex items-center justify-between gap-2 border-b border-border bg-secondary/50 px-3 py-1.5">
        <span className="font-mono text-xs text-muted-foreground">{label}</span>
        <div className="flex items-center gap-1.5">
          {download && (
            <button type="button" onClick={() => downloadText(download.filename, code)} className={cn(outlineBtn, "h-7 text-xs")}>
              <Download className="h-3.5 w-3.5" aria-hidden />
              {download.label}
            </button>
          )}
          <button
            type="button"
            onClick={copy}
            className={cn(outlineBtn, "h-7 w-7 justify-center px-0")}
            aria-label={copied ? t(`${k}.copied`) : t(`${k}.copy`)}
          >
            {copied ? <Check className="h-3.5 w-3.5 text-success" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
          </button>
        </div>
      </div>
      <pre className="max-h-96 overflow-auto bg-background px-4 py-3.5 font-mono text-[12.5px] leading-relaxed">
        <HighlightedCode code={code} language={language} />
      </pre>
    </div>
  );
}

function Warn({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-start gap-2.5 rounded-xl bg-warning/10 px-4 py-3 text-[15px] leading-relaxed">
      <TriangleAlert className="mt-1 h-4 w-4 shrink-0 text-warning" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

/**
 * Guide dialog. Rendered by the upload modal in place of its own dialog (no nested
 * modals); `onClose` brings the admin back to the upload step.
 */
export function CustomMcpGuideDialog({ onClose }: { onClose: () => void }) {
  const t = useT();
  const [templates, setTemplates] = useState<GuideTemplates | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(`${apiBase()}/admin/mcp-custom/guide-template`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as GuideTemplates;
        if (!cancelled) setTemplates(data);
      } catch (err: unknown) {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const body = "text-[15px] leading-relaxed text-muted-foreground";
  const p = (key: string) => <p className={body}>{rich(t(`${k}.${key}`))}</p>;
  const tree = [
    "my-mcp-server/",
    "├── server.py",
    "├── aion-mcp.yaml",
    `├── requirements.txt   # ${t(`${k}.tree_requirements`)}`,
    `├── tools/             # ${t(`${k}.tree_modules`)}`,
    `└── data/              # ${t(`${k}.tree_data`)}`,
  ].join("\n");
  const snippet = (render: (tpl: GuideTemplates) => ReactNode) =>
    templates ? (
      render(templates)
    ) : loadError ? (
      <p className="text-sm text-destructive">{t(`${k}.load_error`, { error: loadError })}</p>
    ) : (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        {t(`${k}.loading`)}
      </p>
    );

  return (
    <Dialog title={t(`${k}.dialog_title`)} closeLabel={t(`${k}.close`)} onClose={onClose} className="max-w-4xl">
      {/* One centred column for text, steps and snippets, with the same width */}
      <div className="flex max-h-[min(75vh,56rem)] flex-col overflow-y-auto pr-1">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 pb-1">
          <p className={body}>{rich(t(`${k}.intro`))}</p>
          <ol className="flex flex-col gap-9">
            <Step n={1} title={t(`${k}.t1`)}>
              {p("b1")}
              <CodeBlock label={t(`${k}.tree_label`)} code={tree} language="tree" />
            </Step>
            <Step n={2} title={t(`${k}.t2`)}>
              {p("b2")}
              <ul className={cn(body, "flex list-disc flex-col gap-1.5 pl-5")}>
                <li>{rich(t(`${k}.rule_stdio`))}</li>
                <li>{rich(t(`${k}.rule_credentials`))}</li>
                <li>{rich(t(`${k}.rule_stdout`))}</li>
                <li>{rich(t(`${k}.rule_paths`))}</li>
                <li>{rich(t(`${k}.rule_names`))}</li>
                <li>{rich(t(`${k}.rule_libraries`))}</li>
              </ul>
              {snippet((tpl) => (
                <CodeBlock label="server.py" code={tpl.server_py} language="python" />
              ))}
            </Step>
            <Step n={3} title={t(`${k}.t3`)}>
              {p("b3")}
              {snippet((tpl) => (
                <CodeBlock
                  label="aion-mcp.yaml"
                  code={tpl.aion_mcp_yaml}
                  language="yaml"
                  download={{ filename: "aion-mcp.yaml", label: t(`${k}.download_yaml`) }}
                />
              ))}
              {p("b3_after")}
            </Step>
            <Step n={4} title={t(`${k}.t4`)}>
              {p("b4")}
              <CodeBlock label={t(`${k}.terminal`)} code={"pip install fastmcp -r requirements.txt\nfastmcp dev server.py"} language="bash" />
            </Step>
            <Step n={5} title={t(`${k}.t5`)}>
              {p("b5")}
            </Step>
            <Step n={6} title={t(`${k}.t6`)}>
              {p("b6")}
            </Step>
            <Step n={7} title={t(`${k}.t7`)}>
              {p("b7")}
            </Step>
          </ol>
          <Warn>{rich(t(`${k}.limits`))}</Warn>
        </div>
      </div>
    </Dialog>
  );
}
