"use client";

import { useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { BarChart3, Check, Copy, Download } from "lucide-react";
import { useT } from "@/lib/i18n/use-t";
import { fileUrl } from "./files";

const isRemote = (s: string) => /^(https?:|data:)/i.test(s);

function Img({ src, alt }: { src?: string | Blob; alt?: string }) {
  const t = useT();
  const [failed, setFailed] = useState(false);
  if (typeof src !== "string" || !src) return null;
  if (failed) {
    return (
      <span className="my-2 inline-flex items-center gap-2 rounded-xl border border-border bg-secondary/50 px-3 py-1.5 text-xs text-muted-foreground">
        <BarChart3 className="h-3.5 w-3.5 shrink-0" aria-hidden />
        {t("admin_diagnostics.markdown.image_error", { name: alt || src.split("/").pop() || "" })}
      </span>
    );
  }
  return (
    <span className="my-3 block">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={isRemote(src) ? src : fileUrl(src)}
        alt={alt || ""}
        loading="lazy"
        onError={() => setFailed(true)}
        className="max-h-[28rem] w-auto max-w-full rounded-2xl border border-border bg-card object-contain"
      />
      {alt && <span className="mt-1.5 block text-center text-xs text-muted-foreground">{alt}</span>}
    </span>
  );
}

function Anchor({ href, children }: { href?: string; children?: React.ReactNode }) {
  if (!href) return <a>{children}</a>;
  if (isRemote(href) || href.startsWith("#") || href.startsWith("mailto:")) {
    return (
      <a href={href} target={href.startsWith("#") ? undefined : "_blank"} rel="noopener noreferrer">
        {children}
      </a>
    );
  }
  // Relative links point at files the agent wrote in its sandbox.
  return (
    <a href={fileUrl(href, true)} download target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-mono text-[0.9em]">
      {children}
      <Download className="h-3 w-3 opacity-70" aria-hidden />
    </a>
  );
}

function Pre({ children }: { children?: React.ReactNode }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const text = (() => {
    const child = Array.isArray(children) ? children[0] : children;
    const inner = (child as { props?: { children?: unknown } } | undefined)?.props?.children;
    return typeof inner === "string" ? inner : Array.isArray(inner) ? inner.join("") : "";
  })();
  return (
    <div className="group relative my-3 overflow-hidden rounded-xl border border-border bg-muted/50">
      {text && (
        <button
          type="button"
          onClick={() => {
            navigator.clipboard.writeText(text);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1600);
          }}
          className="focus-ring absolute right-2 top-2 inline-flex h-7 items-center gap-1.5 rounded-lg border border-border bg-card px-2 text-[11px] font-medium text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
        >
          {copied ? <Check className="h-3 w-3 text-success" aria-hidden /> : <Copy className="h-3 w-3" aria-hidden />}
          {copied ? t("admin_diagnostics.markdown.copied") : t("admin_diagnostics.markdown.copy")}
        </button>
      )}
      <pre className="max-h-[30rem] overflow-auto p-4 font-mono text-xs leading-relaxed">{children}</pre>
    </div>
  );
}

const components: Components = {
  img: ({ src, alt }) => <Img src={src} alt={alt} />,
  a: ({ href, children }) => <Anchor href={href}>{children}</Anchor>,
  pre: ({ children }) => <Pre>{children}</Pre>,
  table: (p) => (
    <div className="table-wrapper">
      <table {...p} />
    </div>
  ),
};

/** The same markdown surface as the chat transcript (`.prose-chat`), with sandbox files resolved through the admin API. */
export function Markdown({ children, className = "" }: { children: string; className?: string }) {
  return (
    <div className={`prose-chat chat-font break-words text-sm ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
