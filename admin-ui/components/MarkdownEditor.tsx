"use client";

import { useRef, useCallback, useEffect, KeyboardEvent, useState } from "react";
import {
  Bold,
  Italic,
  Code,
  Heading1,
  Heading2,
  Heading3,
  Link,
  Quote,
  List,
  ListOrdered,
  Minus,
  Code2,
  Hash,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────────────

interface MarkdownEditorProps {
  value: string;
  onChange: (val: string) => void;
  height?: number;
  placeholder?: string;
  className?: string;
}

// ─── Syntax Highlight ────────────────────────────────────────────────────────

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function applyHighlight(raw: string): string {
  const lines = raw.split("\n");

  const highlighted = lines.map((line) => {
    // Headings
    if (/^#{1,6} /.test(line)) {
      const level = (line.match(/^(#+)/) || ["", ""])[1].length;
      const colors: Record<number, string> = {
        1: "#60a5fa",
        2: "#818cf8",
        3: "#a78bfa",
        4: "#c084fc",
        5: "#e879f9",
        6: "#f472b6",
      };
      const color = colors[level] || "#60a5fa";
      const escaped = escapeHtml(line);
      return `<span style="color:${color};font-weight:700">${escaped}</span>`;
    }

    // Blockquote lines
    if (/^> /.test(line)) {
      const escaped = escapeHtml(line);
      return `<span style="color:#6b7280;font-style:italic">${escaped}</span>`;
    }

    // Horizontal rule
    if (/^---\s*$/.test(line)) {
      const escaped = escapeHtml(line);
      return `<span style="color:#374151">${escaped}</span>`;
    }

    // Unordered list marker
    let processed = escapeHtml(line);

    // Code blocks (fenced) — mark entire line in green
    if (/^```/.test(line)) {
      return `<span style="color:#34d399">${processed}</span>`;
    }

    // Bold **text**
    processed = processed.replace(
      /\*\*(.+?)\*\*/g,
      '<span style="color:#fde68a;font-weight:700">**$1**</span>'
    );

    // Italic *text* (not inside **)
    processed = processed.replace(
      /(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g,
      '<span style="color:#fdba74;font-style:italic">*$1*</span>'
    );

    // Inline code `text`
    processed = processed.replace(
      /`([^`]+)`/g,
      '<span style="color:#6ee7b7;background:rgba(52,211,153,0.08);border-radius:3px">`$1`</span>'
    );

    // Links [text](url)
    processed = processed.replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      '<span style="color:#38bdf8;text-decoration:underline">[$1]($2)</span>'
    );

    // List markers - and *
    processed = processed.replace(
      /^(\s*)([-*]) /,
      '$1<span style="color:#94a3b8">$2</span> '
    );

    // Ordered list markers
    processed = processed.replace(
      /^(\s*)(\d+\.) /,
      '$1<span style="color:#94a3b8">$2</span> '
    );

    return processed;
  });

  return highlighted.join("\n");
}

// ─── Toolbar Config ───────────────────────────────────────────────────────────

interface ToolbarAction {
  id: string;
  label: string;
  icon: React.ReactNode;
  prefix: string;
  suffix: string;
  placeholder: string;
  block?: boolean;
}

const TOOLBAR_ACTIONS: ToolbarAction[] = [
  {
    id: "h1",
    label: "Heading 1",
    icon: <Heading1 className="w-3.5 h-3.5" />,
    prefix: "# ",
    suffix: "",
    placeholder: "Heading",
    block: true,
  },
  {
    id: "h2",
    label: "Heading 2",
    icon: <Heading2 className="w-3.5 h-3.5" />,
    prefix: "## ",
    suffix: "",
    placeholder: "Heading",
    block: true,
  },
  {
    id: "h3",
    label: "Heading 3",
    icon: <Heading3 className="w-3.5 h-3.5" />,
    prefix: "### ",
    suffix: "",
    placeholder: "Heading",
    block: true,
  },
  {
    id: "bold",
    label: "Bold (Ctrl+B)",
    icon: <Bold className="w-3.5 h-3.5" />,
    prefix: "**",
    suffix: "**",
    placeholder: "bold text",
  },
  {
    id: "italic",
    label: "Italic (Ctrl+I)",
    icon: <Italic className="w-3.5 h-3.5" />,
    prefix: "*",
    suffix: "*",
    placeholder: "italic text",
  },
  {
    id: "code",
    label: "Inline Code (Ctrl+E)",
    icon: <Code className="w-3.5 h-3.5" />,
    prefix: "`",
    suffix: "`",
    placeholder: "code",
  },
  {
    id: "codeblock",
    label: "Code Block",
    icon: <Code2 className="w-3.5 h-3.5" />,
    prefix: "```\n",
    suffix: "\n```",
    placeholder: "code block",
  },
  {
    id: "link",
    label: "Link",
    icon: <Link className="w-3.5 h-3.5" />,
    prefix: "[",
    suffix: "](url)",
    placeholder: "link text",
  },
  {
    id: "quote",
    label: "Blockquote",
    icon: <Quote className="w-3.5 h-3.5" />,
    prefix: "> ",
    suffix: "",
    placeholder: "quote",
    block: true,
  },
  {
    id: "ul",
    label: "Unordered List",
    icon: <List className="w-3.5 h-3.5" />,
    prefix: "- ",
    suffix: "",
    placeholder: "list item",
    block: true,
  },
  {
    id: "ol",
    label: "Ordered List",
    icon: <ListOrdered className="w-3.5 h-3.5" />,
    prefix: "1. ",
    suffix: "",
    placeholder: "list item",
    block: true,
  },
  {
    id: "hr",
    label: "Horizontal Rule",
    icon: <Minus className="w-3.5 h-3.5" />,
    prefix: "\n---\n",
    suffix: "",
    placeholder: "",
    block: true,
  },
];

// ─── Toolbar Separators ───────────────────────────────────────────────────────

const SEPARATOR_AFTER = new Set(["h3", "code", "codeblock", "link", "ul", "ol"]);

// ─── Component ────────────────────────────────────────────────────────────────

export function MarkdownEditor({
  value,
  onChange,
  height = 550,
  placeholder = "Write your Markdown here...",
  className = "",
}: MarkdownEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const highlightRef = useRef<HTMLDivElement>(null);
  const [isFocused, setIsFocused] = useState(false);

  // Sync highlight layer scroll with textarea
  const syncScroll = useCallback(() => {
    if (!textareaRef.current || !highlightRef.current) return;
    highlightRef.current.scrollTop = textareaRef.current.scrollTop;
    highlightRef.current.scrollLeft = textareaRef.current.scrollLeft;
  }, []);

  // ── Insert Markdown syntax around selection ──────────────────────────────
  const insertSyntax = useCallback(
    (action: ToolbarAction) => {
      const ta = textareaRef.current;
      if (!ta) return;

      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const selected = value.slice(start, end);
      const before = value.slice(0, start);
      const after = value.slice(end);

      let inserted: string;
      let newCursorStart: number;
      let newCursorEnd: number;

      if (selected) {
        inserted = `${action.prefix}${selected}${action.suffix}`;
        newCursorStart = start + action.prefix.length;
        newCursorEnd = end + action.prefix.length;
      } else {
        inserted = `${action.prefix}${action.placeholder}${action.suffix}`;
        newCursorStart = start + action.prefix.length;
        newCursorEnd = newCursorStart + action.placeholder.length;
      }

      const newValue = before + inserted + after;
      onChange(newValue);

      // Restore focus + selection after React re-render
      requestAnimationFrame(() => {
        ta.focus();
        ta.setSelectionRange(newCursorStart, newCursorEnd);
      });
    },
    [value, onChange]
  );

  // ── Keyboard shortcuts ───────────────────────────────────────────────────
  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      const ta = textareaRef.current;
      if (!ta) return;

      // Ctrl+B → Bold
      if ((e.ctrlKey || e.metaKey) && e.key === "b") {
        e.preventDefault();
        insertSyntax(TOOLBAR_ACTIONS.find((a) => a.id === "bold")!);
        return;
      }

      // Ctrl+I → Italic
      if ((e.ctrlKey || e.metaKey) && e.key === "i") {
        e.preventDefault();
        insertSyntax(TOOLBAR_ACTIONS.find((a) => a.id === "italic")!);
        return;
      }

      // Ctrl+E → Inline code
      if ((e.ctrlKey || e.metaKey) && e.key === "e") {
        e.preventDefault();
        insertSyntax(TOOLBAR_ACTIONS.find((a) => a.id === "code")!);
        return;
      }

      // Tab → indent 2 spaces
      if (e.key === "Tab") {
        e.preventDefault();
        const start = ta.selectionStart;
        const end = ta.selectionEnd;
        if (e.shiftKey) {
          // Deindent: remove up to 2 leading spaces
          const lineStart = value.lastIndexOf("\n", start - 1) + 1;
          const lineText = value.slice(lineStart, end);
          const deindented = lineText.replace(/^ {1,2}/, "");
          const removed = lineText.length - deindented.length;
          const newValue =
            value.slice(0, lineStart) + deindented + value.slice(end);
          onChange(newValue);
          requestAnimationFrame(() => {
            ta.setSelectionRange(Math.max(start - removed, lineStart), end - removed);
          });
        } else {
          const newValue = value.slice(0, start) + "  " + value.slice(end);
          onChange(newValue);
          requestAnimationFrame(() => {
            ta.setSelectionRange(start + 2, start + 2);
          });
        }
        return;
      }

      // Enter → continue list if in a list
      if (e.key === "Enter") {
        const start = ta.selectionStart;
        const lineStart = value.lastIndexOf("\n", start - 1) + 1;
        const currentLine = value.slice(lineStart, start);

        const ulMatch = currentLine.match(/^(\s*)([-*]) /);
        const olMatch = currentLine.match(/^(\s*)(\d+)\. /);

        if (ulMatch) {
          // Empty list item → break out
          if (currentLine.trim() === ulMatch[2]) {
            e.preventDefault();
            const newValue =
              value.slice(0, lineStart) + "\n" + value.slice(start);
            onChange(newValue);
            requestAnimationFrame(() => {
              ta.setSelectionRange(lineStart + 1, lineStart + 1);
            });
          } else {
            e.preventDefault();
            const continuation = `\n${ulMatch[1]}${ulMatch[2]} `;
            const newValue =
              value.slice(0, start) + continuation + value.slice(start);
            onChange(newValue);
            requestAnimationFrame(() => {
              ta.setSelectionRange(
                start + continuation.length,
                start + continuation.length
              );
            });
          }
          return;
        }

        if (olMatch) {
          e.preventDefault();
          const nextNum = parseInt(olMatch[2], 10) + 1;
          const continuation = `\n${olMatch[1]}${nextNum}. `;
          const newValue =
            value.slice(0, start) + continuation + value.slice(start);
          onChange(newValue);
          requestAnimationFrame(() => {
            ta.setSelectionRange(
              start + continuation.length,
              start + continuation.length
            );
          });
          return;
        }
      }
    },
    [value, onChange, insertSyntax]
  );

  // ── Highlight layer content ─────────────────────────────────────────────
  const highlighted = applyHighlight(value);
  // Trailing newline needed to prevent highlight div from collapsing one line short
  const highlightContent = highlighted + "\n";

  // Shared styles for perfect overlay alignment
  const sharedStyle: React.CSSProperties = {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: "13.5px",
    lineHeight: "1.7",
    padding: "16px 20px",
    margin: 0,
    border: "none",
    outline: "none",
    overflowWrap: "break-word",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    tabSize: 2,
    letterSpacing: "0",
  };

  return (
    <div
      className={`flex flex-col rounded-2xl overflow-hidden border ${
        isFocused ? "border-blue-500/60 ring-2 ring-blue-500/15" : "border-white/10"
      } bg-[#0a0a0a] shadow-2xl transition-all duration-200 ${className}`}
    >
      {/* ── Toolbar ─────────────────────────────────────────────────────── */}
      <div className="flex items-center flex-wrap gap-0.5 px-3 py-2 bg-[#111111] border-b border-white/8">
        {TOOLBAR_ACTIONS.map((action) => (
          <div key={action.id} className="flex items-center">
            <button
              type="button"
              title={action.label}
              onClick={() => insertSyntax(action)}
              className="p-1.5 rounded-lg text-gray-400 hover:text-blue-400 hover:bg-blue-500/10 transition-all duration-150 cursor-pointer"
            >
              {action.icon}
            </button>
            {SEPARATOR_AFTER.has(action.id) && (
              <div className="w-px h-4 bg-white/8 mx-1" />
            )}
          </div>
        ))}

        {/* Right: shortcut hint */}
        <div className="ml-auto flex items-center gap-1 text-[10px] text-gray-600 font-mono pr-1">
          <span className="hidden sm:inline">Ctrl+B</span>
          <span className="hidden sm:inline text-gray-700">·</span>
          <span className="hidden sm:inline">Ctrl+I</span>
          <span className="hidden sm:inline text-gray-700">·</span>
          <span className="hidden sm:inline">Ctrl+E</span>
        </div>
      </div>

      {/* ── Editor Area ─────────────────────────────────────────────────── */}
      <div
        className="relative overflow-hidden"
        style={{ height: `${height}px` }}
      >
        {/* Highlight layer (behind textarea) */}
        <div
          ref={highlightRef}
          aria-hidden="true"
          className="absolute inset-0 overflow-auto pointer-events-none select-none"
          style={{
            ...sharedStyle,
            color: "#c9d1d9",
            overflowY: "auto",
            overflowX: "hidden",
          }}
          dangerouslySetInnerHTML={{ __html: highlightContent }}
        />

        {/* Actual textarea (transparent text, visible caret) */}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onScroll={syncScroll}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder={placeholder}
          spellCheck={false}
          autoCapitalize="none"
          autoCorrect="off"
          className="absolute inset-0 w-full h-full resize-none bg-transparent outline-none placeholder:text-gray-700"
          style={{
            ...sharedStyle,
            color: "transparent",
            caretColor: "#60a5fa",
            overflowY: "auto",
            overflowX: "hidden",
          }}
        />
      </div>

      {/* ── Status Bar ──────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-1.5 bg-[#0d0d0d] border-t border-white/5 text-[10px] text-gray-700 font-mono">
        <span>
          {value.split("\n").length} lines · {value.length} chars
        </span>
        <span className="flex items-center gap-1.5 text-gray-700">
          <Hash className="w-3 h-3" />
          Markdown
        </span>
      </div>
    </div>
  );
}
