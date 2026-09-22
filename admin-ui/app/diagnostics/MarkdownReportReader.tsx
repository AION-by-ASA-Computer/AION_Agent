"use client";

import React, { useState, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  FileText,
  Copy,
  Download,
  Check,
  Code,
  Eye,
  Columns2,
  Search,
  X,
  ExternalLink,
  Sparkles,
  Clock,
  Hash,
} from "lucide-react";
import { apiBase } from "@/lib/api";
import { getStoredToken } from "@/lib/auth/storage";

interface MarkdownReportReaderProps {
  content: string;
  reportName?: string;
  onDownload?: (content: string, filename: string) => void;
  className?: string;
}

// Custom Image Component resolving workspace files
function MarkdownImage({ src, alt, ...props }: React.ComponentProps<"img">) {
  const [hasError, setHasError] = useState(false);

  const rawSrc = typeof src === "string" ? src : "";
  let finalSrc = rawSrc;
  if (finalSrc && !finalSrc.startsWith("http://") && !finalSrc.startsWith("https://") && !finalSrc.startsWith("data:")) {
    let cleanPath = finalSrc.replace(/^file:\/\/\/?(app\/)?/i, "");
    cleanPath = cleanPath.replace(/^[./\\]+/, "");
    const token = getStoredToken();
    finalSrc = `${apiBase()}/admin/diagnostics/file?path=${encodeURIComponent(cleanPath)}&access_token=${token || ""}`;
  }

  if (hasError) {
    return (
      <div className="my-4 p-4 rounded-xl bg-red-950/20 border border-red-500/30 text-xs text-red-300 flex items-center gap-2">
        <span>Unable to load image: <code>{alt || rawSrc}</code></span>
      </div>
    );
  }

  return (
    <div className="my-5 rounded-xl overflow-hidden border border-[#2e2e2e] bg-black/40 p-2 shadow-lg">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={finalSrc}
        alt={alt || "Report Image"}
        className="max-w-full h-auto rounded-lg mx-auto object-contain max-h-[500px]"
        onError={() => setHasError(true)}
        {...props}
      />
      {alt && (
        <p className="text-[11px] text-gray-400 text-center mt-2 font-mono italic">
          {alt}
        </p>
      )}
    </div>
  );
}

// Custom Link Component
function MarkdownLink({ href, children, ...props }: React.ComponentProps<"a">) {
  const rawHref = typeof href === "string" ? href : "";
  const isExternal = rawHref.startsWith("http://") || rawHref.startsWith("https://");

  if (isExternal) {
    return (
      <a
        href={rawHref}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-emerald-400 hover:text-emerald-300 underline underline-offset-2 hover:no-underline transition-colors font-medium"
        {...props}
      >
        <span>{children}</span>
        <ExternalLink className="w-3 h-3 opacity-70" />
      </a>
    );
  }

  if (!rawHref || rawHref.startsWith("#") || rawHref.startsWith("mailto:")) {
    return <a href={rawHref} {...props}>{children}</a>;
  }

  let cleanPath = rawHref.replace(/^file:\/\/\/?(app\/)?/i, "");
  cleanPath = cleanPath.replace(/^[./\\]+/, "");

  const token = getStoredToken();
  const downloadUrl = `${apiBase()}/admin/diagnostics/file?path=${encodeURIComponent(cleanPath)}&download=1&access_token=${token || ""}`;

  return (
    <a
      href={downloadUrl}
      download
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-emerald-400 hover:text-emerald-300 underline underline-offset-2 hover:no-underline transition-colors font-medium"
      {...props}
    >
      <span>{children}</span>
      <Download className="w-3 h-3 opacity-70" />
    </a>
  );
}

// Custom Pre / Code block with copy button
function CodeBlock({ children, ...props }: React.ComponentProps<"pre">) {
  const [copied, setCopied] = useState(false);

  // Extract raw text from children if possible
  const getRawText = (): string => {
    if (typeof children === "string") return children;
    if (React.isValidElement(children) && (children.props as any)?.children) {
      const codeChild = (children.props as any).children;
      return typeof codeChild === "string" ? codeChild : String(codeChild || "");
    }
    return "";
  };

  const handleCopy = () => {
    const text = getRawText();
    if (text) {
      navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="relative group my-4 rounded-xl border border-[#2a2a2a] bg-[#0c0c0c] overflow-hidden shadow-inner">
      <div className="flex items-center justify-between px-3.5 py-1.5 bg-[#161616] border-b border-[#242424] text-[11px] font-mono text-gray-400">
        <span className="flex items-center gap-1.5">
          <Code className="w-3.5 h-3.5 text-emerald-400" />
          <span>Code Snippet</span>
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 text-gray-400 hover:text-white px-2 py-0.5 rounded bg-[#202020] hover:bg-[#2a2a2a] border border-[#333] transition-colors cursor-pointer text-[10px]"
        >
          {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
          <span>{copied ? "Copied!" : "Copy"}</span>
        </button>
      </div>
      <pre className="p-4 overflow-x-auto text-xs font-mono text-gray-200 leading-relaxed max-h-[500px]" {...props}>
        {children}
      </pre>
    </div>
  );
}

export function MarkdownReportReader({
  content,
  reportName = "Smoke Test Execution Report",
  onDownload,
  className = "",
}: MarkdownReportReaderProps) {
  const [viewMode, setViewMode] = useState<"preview" | "raw" | "split">("preview");
  const [copied, setCopied] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [showSearch, setShowSearch] = useState(false);

  // Statistics
  const stats = useMemo(() => {
    if (!content) return { words: 0, chars: 0, lines: 0, readingTime: 0 };
    const words = content.trim().split(/\s+/).filter(Boolean).length;
    const chars = content.length;
    const lines = content.split("\n").length;
    const readingTime = Math.max(1, Math.ceil(words / 200));
    return { words, chars, lines, readingTime };
  }, [content]);

  const handleCopyMarkdown = async () => {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error("Failed to copy markdown:", e);
    }
  };

  const handleDownload = () => {
    if (onDownload) {
      onDownload(content, reportName);
    } else {
      const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = reportName.endsWith(".md") ? reportName : `${reportName}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
  };

  // Rich markdown custom components styling
  const customMarkdownComponents = useMemo(() => {
    return {
      img: MarkdownImage,
      a: MarkdownLink,
      pre: CodeBlock,
      code: ({ inline, className: codeClass, children, ...props }: any) => {
        return (
          <code
            className="font-mono text-[0.88em] bg-[#1a1a1a] text-amber-300 border border-[#333] rounded px-1.5 py-0.5"
            {...props}
          >
            {children}
          </code>
        );
      },
      h1: ({ children, ...props }: any) => (
        <h1
          className="text-xl sm:text-2xl font-bold text-white border-b border-[#2e2e2e] pb-3 mb-4 mt-6 first:mt-0 flex items-center gap-2"
          {...props}
        >
          <Sparkles className="w-5 h-5 text-emerald-400 shrink-0" />
          <span>{children}</span>
        </h1>
      ),
      h2: ({ children, ...props }: any) => (
        <h2
          className="text-lg font-bold text-white mt-7 mb-3 pb-2 border-b border-[#242424] flex items-center gap-2 text-emerald-400"
          {...props}
        >
          <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block shrink-0" />
          <span>{children}</span>
        </h2>
      ),
      h3: ({ children, ...props }: any) => (
        <h3 className="text-base font-semibold text-gray-100 mt-5 mb-2 flex items-center gap-1.5" {...props}>
          <span className="text-gray-500 font-mono text-sm">›</span>
          <span>{children}</span>
        </h3>
      ),
      h4: ({ children, ...props }: any) => (
        <h4 className="text-sm font-semibold text-gray-200 mt-4 mb-1.5" {...props}>
          {children}
        </h4>
      ),
      p: ({ children, ...props }: any) => (
        <p className="text-sm text-gray-300 leading-relaxed mb-3.5 font-sans" {...props}>
          {children}
        </p>
      ),
      ul: ({ children, ...props }: any) => (
        <ul className="list-disc list-inside space-y-1.5 text-sm text-gray-300 my-3 pl-2" {...props}>
          {children}
        </ul>
      ),
      ol: ({ children, ...props }: any) => (
        <ol className="list-decimal list-inside space-y-1.5 text-sm text-gray-300 my-3 pl-2" {...props}>
          {children}
        </ol>
      ),
      li: ({ children, ...props }: any) => (
        <li className="text-sm text-gray-300 leading-relaxed" {...props}>
          {children}
        </li>
      ),
      table: ({ children, ...props }: any) => (
        <div className="my-5 rounded-xl border border-[#2b2b2b] overflow-x-auto bg-[#101010] shadow-sm">
          <table className="w-full text-left text-xs border-collapse divide-y divide-[#262626]" {...props}>
            {children}
          </table>
        </div>
      ),
      thead: ({ children, ...props }: any) => (
        <thead className="bg-[#181818] text-gray-200 font-semibold" {...props}>
          {children}
        </thead>
      ),
      tbody: ({ children, ...props }: any) => (
        <tbody className="divide-y divide-[#202020] text-gray-300 font-sans" {...props}>
          {children}
        </tbody>
      ),
      tr: ({ children, ...props }: any) => (
        <tr className="hover:bg-white/[0.02] transition-colors" {...props}>
          {children}
        </tr>
      ),
      th: ({ children, ...props }: any) => (
        <th className="px-4 py-3 text-xs font-semibold text-gray-200 border-b border-[#2b2b2b] tracking-wider" {...props}>
          {children}
        </th>
      ),
      td: ({ children, ...props }: any) => (
        <td className="px-4 py-2.5 text-xs text-gray-300 border-t border-[#1f1f1f] leading-normal" {...props}>
          {children}
        </td>
      ),
      blockquote: ({ children, ...props }: any) => (
        <blockquote
          className="border-l-4 border-emerald-500 bg-emerald-950/20 px-4 py-3 rounded-r-xl my-4 text-sm text-emerald-200/90 italic"
          {...props}
        >
          {children}
        </blockquote>
      ),
      hr: ({ ...props }: any) => <hr className="border-[#262626] my-6" {...props} />,
      strong: ({ children, ...props }: any) => (
        <strong className="font-semibold text-white" {...props}>
          {children}
        </strong>
      ),
      em: ({ children, ...props }: any) => (
        <em className="italic text-gray-300" {...props}>
          {children}
        </em>
      ),
      del: ({ children, ...props }: any) => (
        <del className="line-through text-gray-500" {...props}>
          {children}
        </del>
      ),
    };
  }, []);

  return (
    <div className={`rounded-xl border border-[#262626] bg-[#141414] overflow-hidden flex flex-col shadow-xl ${className}`}>
      {/* Top Document Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-5 py-3.5 border-b border-[#262626] bg-[#181818]">
        {/* Document Title & Meta */}
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shrink-0">
            <FileText className="w-4 h-4" />
          </div>
          <div className="min-w-0 truncate">
            <h3 className="font-bold text-sm text-white truncate flex items-center gap-2">
              <span>{reportName || "Smoke Test Execution Report"}</span>
              <span className="text-[10px] px-2 py-0.5 rounded-full font-mono bg-[#222] text-gray-400 border border-[#333]">
                Markdown Reader
              </span>
            </h3>
            <div className="flex items-center gap-3 text-[11px] text-gray-400 mt-0.5 font-mono">
              <span className="flex items-center gap-1">
                <Hash className="w-3 h-3 text-gray-500" />
                {stats.words.toLocaleString()} words &bull; {stats.lines} lines
              </span>
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3 text-gray-500" />
                ~{stats.readingTime} min read
              </span>
            </div>
          </div>
        </div>

        {/* Reader Controls & Actions */}
        <div className="flex items-center gap-2 shrink-0 flex-wrap">
          {/* Mode Switcher */}
          <div className="flex items-center bg-[#111] p-1 rounded-lg border border-[#2a2a2a]">
            <button
              type="button"
              onClick={() => setViewMode("preview")}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-all cursor-pointer ${
                viewMode === "preview"
                  ? "bg-emerald-600 text-white shadow-sm"
                  : "text-gray-400 hover:text-gray-200"
              }`}
              title="Rendered Document Preview"
            >
              <Eye className="w-3.5 h-3.5" />
              <span className="hidden md:inline">Preview</span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode("split")}
              className={`hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-all cursor-pointer ${
                viewMode === "split"
                  ? "bg-emerald-600 text-white shadow-sm"
                  : "text-gray-400 hover:text-gray-200"
              }`}
              title="Side-by-side Split View"
            >
              <Columns2 className="w-3.5 h-3.5" />
              <span>Split</span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode("raw")}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-all cursor-pointer ${
                viewMode === "raw"
                  ? "bg-emerald-600 text-white shadow-sm"
                  : "text-gray-400 hover:text-gray-200"
              }`}
              title="Raw Markdown Source"
            >
              <Code className="w-3.5 h-3.5" />
              <span className="hidden md:inline">Source</span>
            </button>
          </div>

          {/* Search Toggle */}
          <button
            type="button"
            onClick={() => setShowSearch(!showSearch)}
            className={`p-1.5 rounded-lg border transition-all cursor-pointer text-xs ${
              showSearch || searchQuery
                ? "bg-[#252525] border-emerald-500/40 text-emerald-400"
                : "bg-[#1d1d1d] hover:bg-[#252525] border-[#303030] text-gray-400 hover:text-white"
            }`}
            title="Search in document"
          >
            <Search className="w-3.5 h-3.5" />
          </button>

          {/* Copy Button */}
          {content && (
            <button
              type="button"
              onClick={handleCopyMarkdown}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-[#1e1e1e] hover:bg-[#262626] text-gray-200 border border-[#333] transition-all cursor-pointer shadow-sm"
              title="Copy full Markdown document to clipboard"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copied ? "Copied!" : "Copy MD"}</span>
            </button>
          )}

          {/* Download Button */}
          {content && (
            <button
              type="button"
              onClick={handleDownload}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-600 hover:bg-emerald-500 text-white transition-all cursor-pointer shadow"
              title="Download as .md file"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Download .md</span>
            </button>
          )}
        </div>
      </div>

      {/* Optional In-Document Search Bar */}
      {showSearch && (
        <div className="px-5 py-2.5 bg-[#121212] border-b border-[#222] flex items-center gap-2 animate-in fade-in duration-150">
          <Search className="w-3.5 h-3.5 text-gray-400 shrink-0" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search keywords in markdown report..."
            className="w-full bg-transparent text-xs text-white placeholder-gray-500 focus:outline-none font-mono"
            autoFocus
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="text-gray-400 hover:text-white p-0.5 rounded cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* Reader Content Body */}
      <div className="flex-1 min-h-[400px] overflow-hidden">
        {!content ? (
          <div className="py-20 text-center text-gray-500 font-sans flex flex-col items-center justify-center gap-3">
            <FileText className="w-8 h-8 text-gray-600 stroke-1" />
            <p className="text-sm">No report generated or selected.</p>
            <p className="text-xs text-gray-600">Run a test suite or select a report from the history list.</p>
          </div>
        ) : viewMode === "preview" ? (
          /* Rendered Mode */
          <div className="p-6 sm:p-8 overflow-y-auto max-h-[720px] bg-[#141414]">
            <div className="max-w-4xl mx-auto">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={customMarkdownComponents}>
                {content}
              </ReactMarkdown>
            </div>
          </div>
        ) : viewMode === "raw" ? (
          /* Raw Markdown Mode */
          <div className="p-5 overflow-y-auto max-h-[720px] bg-[#0c0c0c] font-mono text-xs">
            <div className="flex">
              {/* Line Numbers */}
              <div className="select-none pr-4 text-right text-gray-600 font-mono text-xs border-r border-[#202020] mr-4 shrink-0">
                {content.split("\n").map((_, i) => (
                  <div key={i} className="leading-relaxed">
                    {i + 1}
                  </div>
                ))}
              </div>
              {/* Code */}
              <pre className="text-emerald-200/90 whitespace-pre-wrap break-all leading-relaxed flex-1 font-mono">
                {content}
              </pre>
            </div>
          </div>
        ) : (
          /* Split View Mode (LG Screens) */
          <div className="grid grid-cols-2 divide-x divide-[#262626] max-h-[720px] h-full overflow-hidden">
            {/* Left: Raw */}
            <div className="p-5 overflow-y-auto bg-[#0c0c0c] font-mono text-xs">
              <div className="text-[10px] text-gray-500 font-mono mb-2 uppercase tracking-wider">Raw Markdown (.md)</div>
              <pre className="text-gray-300 whitespace-pre-wrap break-all leading-relaxed font-mono">
                {content}
              </pre>
            </div>
            {/* Right: Rendered */}
            <div className="p-6 overflow-y-auto bg-[#141414]">
              <div className="text-[10px] text-emerald-400 font-mono mb-3 uppercase tracking-wider">Rendered Preview</div>
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={customMarkdownComponents}>
                {content}
              </ReactMarkdown>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
