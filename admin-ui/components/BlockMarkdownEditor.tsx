"use client";

import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { 
  Type, 
  Heading1, 
  Heading2, 
  Heading3, 
  CheckSquare, 
  Code as CodeIcon, 
  List as ListIcon 
} from "lucide-react";

// --- Inline Markdown Preview ---

/**
 * Renders markdown inline content (bold, italic, code, links) without block-level wrappers.
 * Used in preview mode for non-focused blocks.
 */
const inlineMdComponents: React.ComponentProps<typeof ReactMarkdown>["components"] = {
  // Avoid <p> wrappers for inline content
  p: ({ children }) => <span>{children}</span>,
  strong: ({ children }) => <strong className="font-bold text-white">{children}</strong>,
  em: ({ children }) => <em className="italic text-slate-300">{children}</em>,
  code: ({ children }) => (
    <code className="font-mono text-emerald-300 bg-emerald-500/10 rounded px-1 py-0.5 text-[0.88em] border border-emerald-500/20">
      {children}
    </code>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-400 underline underline-offset-2 hover:text-blue-300 transition-colors"
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </a>
  ),
  del: ({ children }) => <del className="line-through text-slate-500">{children}</del>,
};

// --- Types ---

export type BlockType = "h1" | "h2" | "h3" | "task" | "list" | "code" | "text";

export interface Block {
  id: string;
  type: BlockType;
  content: string;
  checked?: boolean;
}

interface BlockMarkdownEditorProps {
  value: string;
  onChange: (val: string) => void;
  placeholder?: string;
  height?: number;
  readOnly?: boolean;
  allowTasks?: boolean;
}

// --- Utils ---

const generateId = () => Math.random().toString(36).substr(2, 9);

const parseMarkdownToBlocks = (md: string, allowTasks: boolean = true): Block[] => {
  if (!md) return [{ id: generateId(), type: "text", content: "" }];
  
  const lines = md.split("\n");
  const newBlocks: Block[] = [];
  let currentCodeBlock: Block | null = null;

  lines.forEach((line) => {
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (currentCodeBlock) {
        newBlocks.push(currentCodeBlock);
        currentCodeBlock = null;
      } else {
        currentCodeBlock = { id: generateId(), type: "code", content: "" };
      }
      return;
    }

    if (currentCodeBlock) {
      currentCodeBlock.content += (currentCodeBlock.content ? "\n" : "") + line;
      return;
    }

    if (line.startsWith("# ")) {
      newBlocks.push({ id: generateId(), type: "h1", content: line.slice(2) });
    } else if (line.startsWith("## ")) {
      newBlocks.push({ id: generateId(), type: "h2", content: line.slice(3) });
    } else if (line.startsWith("### ")) {
      newBlocks.push({ id: generateId(), type: "h3", content: line.slice(4) });
    } else if (allowTasks && (line.startsWith("- [ ] ") || line.startsWith("- [x] "))) {
      newBlocks.push({
        id: generateId(),
        type: "task",
        content: line.slice(6),
        checked: line.startsWith("- [x] "),
      });
    } else if (line.startsWith("- ")) {
      newBlocks.push({ id: generateId(), type: "list", content: line.slice(2) });
    } else if (trimmed !== "" || (newBlocks.length > 0 && newBlocks[newBlocks.length-1].content !== "")) {
        newBlocks.push({ id: generateId(), type: "text", content: line });
    } else if (trimmed === "" && (newBlocks.length === 0 || newBlocks[newBlocks.length-1].type !== "text" || newBlocks[newBlocks.length-1].content !== "")) {
        newBlocks.push({ id: generateId(), type: "text", content: "" });
    }
  });

  if (currentCodeBlock) newBlocks.push(currentCodeBlock);
  return newBlocks.length > 0 ? newBlocks : [{ id: generateId(), type: "text", content: "" }];
};

const serializeBlocksToMarkdown = (blks: Block[]): string => {
  return blks
    .map((b) => {
      switch (b.type) {
        case "h1": return `# ${b.content}`;
        case "h2": return `## ${b.content}`;
        case "h3": return `### ${b.content}`;
        case "task": return `- [${b.checked ? "x" : " "}] ${b.content}`;
        case "list": return `- ${b.content}`;
        case "code": return `\`\`\`\n${b.content}\n\`\`\``;
        default: return b.content;
      }
    })
    .join("\n");
};

const foldPlainYamlText = (content: string): string => {
  const lines = content.split("\n");
  let result = "";
  let isPrevLineEmpty = false;
  let inCodeBlock = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmedLine = line.trim();

    if (trimmedLine.startsWith("```")) {
      inCodeBlock = !inCodeBlock;
    }

    const isBlockPrefix = /^(#+\s|-\s|-\s\[[ x]\]\s|```|\*\s|\d+\.\s|>\s)/.test(line.trimStart());

    if (trimmedLine === "") {
      if (!isPrevLineEmpty && result !== "") {
        result += "\n";
      }
      isPrevLineEmpty = true;
    } else {
      if (result === "") {
        result = line.trim();
      } else if (isPrevLineEmpty || isBlockPrefix || inCodeBlock || (lines[i - 1] && lines[i - 1].trim().startsWith("```"))) {
        // If we are inside a code block, or the previous line starts/ends a code block,
        // or this line starts a block markdown element, preserve the newline.
        result += "\n" + (inCodeBlock ? line : line.trim());
      } else {
        const separator = result.endsWith(" ") ? "" : " ";
        result += separator + line.trim();
      }
      isPrevLineEmpty = false;
    }
  }
  return result;
};

const stripCommonIndentation = (text: string): string => {
  const lines = text.split("\n");
  let minIndent = Infinity;
  for (const line of lines) {
    if (line.trim() === "") continue;
    const match = line.match(/^(\s*)/);
    if (match) {
      minIndent = Math.min(minIndent, match[0].length);
    }
  }
  
  if (minIndent === Infinity || minIndent === 0) return text;
  
  return lines.map(line => line.startsWith(" ".repeat(minIndent)) ? line.slice(minIndent) : line.trimStart()).join("\n");
};

const parseYamlScalar = (text: string): string => {
  const trimmed = text.trim();
  
  // 1. Single-quoted scalar
  if (trimmed.startsWith("'") && trimmed.endsWith("'") && trimmed.length >= 2) {
    const content = trimmed.slice(1, -1).replace(/''/g, "'");
    return foldPlainYamlText(content);
  }
  
  // 2. Double-quoted scalar
  if (trimmed.startsWith('"') && trimmed.endsWith('"') && trimmed.length >= 2) {
    const content = trimmed.slice(1, -1)
                           .replace(/\\"/g, '"')
                           .replace(/\\n/g, '\n')
                           .replace(/\\t/g, '\t')
                           .replace(/\\\\/g, '\\');
    return foldPlainYamlText(content);
  }
  
  // 3. Literal block scalar (|)
  if (/^\|[-+]?(\s*\n)/.test(trimmed)) {
    const firstNewlineIndex = trimmed.indexOf("\n");
    if (firstNewlineIndex !== -1) {
      const content = trimmed.slice(firstNewlineIndex + 1);
      return stripCommonIndentation(content);
    }
  }
  
  // 4. Folded block scalar (>)
  if (/^>[-+]?(\s*\n)/.test(trimmed)) {
    const firstNewlineIndex = trimmed.indexOf("\n");
    if (firstNewlineIndex !== -1) {
      const content = trimmed.slice(firstNewlineIndex + 1);
      const stripped = stripCommonIndentation(content);
      return foldPlainYamlText(stripped);
    }
  }
  
  // 5. Plain text / unquoted scalar
  return foldPlainYamlText(text);
};

const normalizePastedText = (text: string): string => {
  let processedText = text;
  
  const instructionsMatch = processedText.match(/^\s*instructions:\s*([\s\S]*)/i);
  if (instructionsMatch) {
    processedText = instructionsMatch[1];
  }
  
  return parseYamlScalar(processedText);
};

// --- Sub-components ---

const BlockNode = React.memo(({
  block,
  isFocused,
  isLocked,
  showSlashMenu,
  onFocus,
  updateBlock,
  addBlock,
  removeBlock,
  moveFocus,
  setShowSlashMenu,
  changeBlockType,
  performUndo,
  performRedo,
  allowTasks = true,
  pasteBlocks,
  selectAll,
}: {
  block: Block;
  isFocused: boolean;
  isLocked: boolean;
  showSlashMenu: boolean;
  onFocus: () => void;
  updateBlock: (id: string, updates: Partial<Block>) => void;
  addBlock: (afterId: string, type?: BlockType, content?: string) => void;
  removeBlock: (id: string) => void;
  moveFocus: (id: string, direction: number) => void;
  setShowSlashMenu: (id: string | null) => void;
  changeBlockType: (id: string, type: BlockType, newContent?: string) => void;
  performUndo: () => void;
  performRedo: () => void;
  allowTasks?: boolean;
  pasteBlocks: (id: string, text: string, selectionStart: number, selectionEnd: number) => void;
  selectAll: () => void;
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [menuIndex, setMenuIndex] = useState(0);

  const menuOptions = useMemo(() => {
    const opts = [
      { id: "text", label: "Text", icon: <Type className="w-4 h-4" /> },
      { id: "h1", label: "Heading 1", icon: <Heading1 className="w-4 h-4" /> },
      { id: "h2", label: "Heading 2", icon: <Heading2 className="w-4 h-4" /> },
      { id: "h3", label: "Heading 3", icon: <Heading3 className="w-4 h-4" /> },
    ];
    if (allowTasks) {
      opts.push({ id: "task", label: "Task List", icon: <CheckSquare className="w-4 h-4" /> });
    }
    opts.push(
      { id: "list", label: "Bullet List", icon: <ListIcon className="w-4 h-4" /> },
      { id: "code", label: "Code Block", icon: <CodeIcon className="w-4 h-4" /> }
    );
    return opts;
  }, [allowTasks]);

  useEffect(() => {
    if (showSlashMenu) setMenuIndex(0);
  }, [showSlashMenu]);

  const adjustHeight = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "inherit";
      el.style.height = `${el.scrollHeight}px`;
    }
  }, []);

  useEffect(() => {
    if (!isFocused) return;
    // Use rAF to ensure the textarea is mounted in the DOM before focusing
    // (it's conditionally rendered, so it may not exist yet on the same frame).
    // We also call adjustHeight() here because block.content doesn't change
    // during the preview→edit transition, so the content-based effect won't fire.
    const raf = requestAnimationFrame(() => {
      if (textareaRef.current) {
        // Recalculate height first (textarea starts at rows=1 when freshly mounted)
        adjustHeight();
        // Then focus and position cursor
        if (document.activeElement !== textareaRef.current) {
          textareaRef.current.focus();
          const val = textareaRef.current.value;
          textareaRef.current.setSelectionRange(val.length, val.length);
        }
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [isFocused, adjustHeight]);

  useEffect(() => {
    adjustHeight();
  }, [block.content, adjustHeight]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    const resizeObserver = new ResizeObserver(() => adjustHeight());
    resizeObserver.observe(el);
    return () => resizeObserver.disconnect();
  }, [adjustHeight]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (isLocked) return;

    if (showSlashMenu) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMenuIndex((prev) => (prev + 1) % menuOptions.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMenuIndex((prev) => (prev - 1 + menuOptions.length) % menuOptions.length);
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        changeBlockType(block.id, menuOptions[menuIndex].id as BlockType);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setShowSlashMenu(null);
        return;
      }
    }

    const isMod = e.ctrlKey || e.metaKey;
    if (isMod) {
      const lowerKey = e.key.toLowerCase();
      if (lowerKey === "z") {
        e.preventDefault();
        if (e.shiftKey) performRedo();
        else performUndo();
        return;
      } else if (lowerKey === "y") {
        e.preventDefault();
        performRedo();
        return;
      } else if (lowerKey === "a") {
        e.preventDefault();
        selectAll();
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      addBlock(block.id, (allowTasks && block.type === "task") ? "task" : block.type === "list" ? "list" : "text");
    } else if (e.key === "Backspace" && block.content === "") {
      e.preventDefault();
      removeBlock(block.id);
    } else if (e.key === "ArrowUp") {
      if (textareaRef.current?.selectionStart === 0) {
        e.preventDefault();
        moveFocus(block.id, -1);
      }
    } else if (e.key === "ArrowDown") {
      if (textareaRef.current?.selectionStart === block.content.length) {
        e.preventDefault();
        moveFocus(block.id, 1);
      }
    } else if (e.key === "/") {
      setShowSlashMenu(block.id);
    } else if (e.key === "Escape") {
      setShowSlashMenu(null);
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (isLocked) return;
    const val = e.target.value;

    const selStart = e.target.selectionStart;
    let converted = false;
    if (selStart !== null) {
      const textBeforeCursor = val.slice(0, selStart);
      const shortcuts: { prefix: string; type: BlockType }[] = [
        { prefix: "# ", type: "h1" },
        { prefix: "## ", type: "h2" },
        { prefix: "### ", type: "h3" },
        { prefix: "- ", type: "list" },
        { prefix: "``` ", type: "code" },
      ];
      if (allowTasks) {
        shortcuts.push({ prefix: "- [ ] ", type: "task" });
      }

      for (const shortcut of shortcuts) {
        if (textBeforeCursor === shortcut.prefix) {
          const remainingContent = val.slice(selStart);
          changeBlockType(block.id, shortcut.type, remainingContent);
          
          setTimeout(() => {
            if (textareaRef.current) {
              textareaRef.current.focus();
              textareaRef.current.setSelectionRange(0, 0);
            }
          }, 0);
          converted = true;
          break;
        }
      }
    }

    if (!converted) {
      updateBlock(block.id, { content: val });
    }
    if (val === "" && showSlashMenu) {
      setShowSlashMenu(null);
    }
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (isLocked) return;
    const text = e.clipboardData.getData("text");
    if (!text) return;

    const isMultiLine = text.includes("\n");
    const hasBlockMd = /^(#+\s|-\s|-\s\[[ x]\]\s|```)/.test(text);
    const isYaml = /^\s*instructions:/i.test(text) || 
                   (/^\s*'[\s\S]*'\s*$/.test(text) && text.trim().length >= 2) || 
                   (/^\s*"[\s\S]*"\s*$/.test(text) && text.trim().length >= 2) ||
                   /^\s*[|>]/.test(text);

    if (isMultiLine || hasBlockMd || isYaml) {
      e.preventDefault();
      const selStart = textareaRef.current?.selectionStart ?? 0;
      const selEnd = textareaRef.current?.selectionEnd ?? 0;
      pasteBlocks(block.id, text, selStart, selEnd);
    }
  };

  const inputStyles: React.CSSProperties = {
    width: "100%",
    background: "transparent",
    border: "none",
    outline: "none",
    color: "inherit",
    resize: "none",
    overflow: "hidden",
    padding: 0,
    margin: 0,
    lineHeight: 1.6,
    fontFamily: block.type === "code" ? "ui-monospace, monospace" : "inherit",
    fontSize: block.type === "h1" ? "1.875rem" : block.type === "h2" ? "1.5rem" : block.type === "h3" ? "1.25rem" : "1rem",
    fontWeight: block.type.startsWith("h") ? 700 : 400,
    letterSpacing: block.type.startsWith("h") ? "-0.02em" : "normal",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  };

  // ---- Preview rendering (non-focused) ----
  const previewContent = (() => {
    if (block.content === "") {
      // Empty block: show a faint placeholder so the row has height
      return <span className="text-gray-600 select-none">&nbsp;</span>;
    }
    switch (block.type) {
      case "h1":
        return (
          <h1 className="text-3xl font-bold tracking-tight text-white leading-tight">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={inlineMdComponents}>
              {block.content}
            </ReactMarkdown>
          </h1>
        );
      case "h2":
        return (
          <h2 className="text-2xl font-bold tracking-tight text-white leading-tight">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={inlineMdComponents}>
              {block.content}
            </ReactMarkdown>
          </h2>
        );
      case "h3":
        return (
          <h3 className="text-xl font-semibold text-white leading-tight">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={inlineMdComponents}>
              {block.content}
            </ReactMarkdown>
          </h3>
        );
      case "code":
        return (
          <pre className="w-full font-mono text-[0.85rem] text-emerald-300 bg-emerald-950/30 border border-emerald-800/30 rounded-lg px-3 py-2 overflow-x-auto whitespace-pre-wrap break-all leading-relaxed">
            <code>{block.content}</code>
          </pre>
        );
      default:
        // text, list, task → inline markdown
        return (
          <span className="leading-relaxed text-slate-300 text-[1rem]">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={inlineMdComponents}>
              {block.content}
            </ReactMarkdown>
          </span>
        );
    }
  })();

  return (
    <div 
      className={`group flex items-start gap-3 px-3 py-1.5 rounded-lg transition-colors relative cursor-text ${isFocused ? "bg-white/5" : "hover:bg-white/5"}`}
      onClick={(e) => {
        const target = e.target as HTMLElement;
        if (target.tagName === "INPUT" && (target as HTMLInputElement).type === "checkbox") {
          return;
        }
        if (target.closest(".slash-menu-container")) {
          return;
        }
        // Always call onFocus() first to trigger state change (mounts the textarea).
        // The rAF in the useEffect will then focus the textarea once it's in the DOM.
        onFocus();
        if (textareaRef.current && document.activeElement !== textareaRef.current) {
          textareaRef.current.focus();
        }
      }}
    >
      {allowTasks && block.type === "task" && (
        <input
          type="checkbox"
          checked={!!block.checked}
          onChange={(e) => updateBlock(block.id, { checked: e.target.checked })}
          disabled={isLocked}
          className="mt-1.5 w-4 h-4 rounded border-white/20 bg-black/40 text-blue-500 focus:ring-blue-500/20 cursor-pointer disabled:opacity-50"
        />
      )}
      {block.type === "list" && (
        <div className="mt-1.5 text-gray-500">•</div>
      )}

      <div className="flex-1 relative min-w-0">
        {/* EDIT mode: textarea shown only when this block is focused */}
        {isFocused ? (
          <>
            <textarea
              ref={textareaRef}
              value={block.content}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              onFocus={onFocus}
              onPaste={handlePaste}
              readOnly={isLocked}
              rows={1}
              placeholder={!isLocked ? "Type '/' for commands..." : ""}
              style={inputStyles}
              className="placeholder:text-gray-600"
            />

            {showSlashMenu && (
              <div className="absolute top-full left-0 z-50 mt-1 w-56 slash-menu-container rounded-xl shadow-2xl p-1 animate-in fade-in zoom-in-95 duration-100">
                {menuOptions.map((item, idx) => (
                  <button
                    key={item.id}
                    onClick={() => changeBlockType(block.id, item.id as BlockType)}
                    onMouseEnter={() => setMenuIndex(idx)}
                    className={`w-full flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-colors slash-menu-button ${
                      idx === menuIndex ? "active" : ""
                    }`}
                  >
                    <div className={`p-1.5 rounded-md transition-colors slash-menu-icon ${
                      idx === menuIndex ? "active" : ""
                    }`}>
                      {item.icon}
                    </div>
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            )}
          </>
        ) : (
          /* PREVIEW mode: rendered markdown shown when block is not focused */
          <div
            style={{ lineHeight: 1.6 }}
            className="w-full min-h-[1.5rem] cursor-text"
          >
            {previewContent}
          </div>
        )}
      </div>
    </div>
  );
});
BlockNode.displayName = "BlockNode";

// --- Main Component ---

export function BlockMarkdownEditor({
  value,
  onChange,
  placeholder = "Write something...",
  height = 550,
  readOnly = false,
  allowTasks = true,
}: BlockMarkdownEditorProps) {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [showSlashMenu, setShowSlashMenu] = useState<string | null>(null);
  const [lastValue, setLastValue] = useState<string>("");

  const historyRef = useRef<Block[][]>([]);
  const historyPointerRef = useRef<number>(-1);
  const isUndoRedoActionRef = useRef<boolean>(false);
  const syncingFromPropRef = useRef(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (value !== lastValue) {
      syncingFromPropRef.current = true;
      const parsed = parseMarkdownToBlocks(value, allowTasks);
      setBlocks(parsed);
      setLastValue(value);
      historyRef.current = [parsed];
      historyPointerRef.current = 0;
    }
  }, [value, lastValue, allowTasks]);

  useEffect(() => {
    if (syncingFromPropRef.current) {
      syncingFromPropRef.current = false;
      return;
    }
    if (blocks.length === 0) return;
    const md = serializeBlocksToMarkdown(blocks);
    if (md !== lastValue) {
      setLastValue(md);
      onChangeRef.current(md);
    }
  }, [blocks, lastValue]);

  useEffect(() => {
    if (isUndoRedoActionRef.current) {
      isUndoRedoActionRef.current = false;
      return;
    }
    if (blocks.length === 0) return;
    const currentHistory = historyRef.current.slice(0, historyPointerRef.current + 1);
    const lastState = currentHistory[currentHistory.length - 1];
    if (lastState && JSON.stringify(lastState) === JSON.stringify(blocks)) return;
    const nextHistory = [...currentHistory, blocks];
    if (nextHistory.length > 50) nextHistory.shift();
    historyRef.current = nextHistory;
    historyPointerRef.current = nextHistory.length - 1;
  }, [blocks]);

  const performUndo = useCallback(() => {
    if (historyPointerRef.current > 0) {
      historyPointerRef.current -= 1;
      const prevState = historyRef.current[historyPointerRef.current];
      isUndoRedoActionRef.current = true;
      setBlocks(prevState);
    }
  }, []);

  const performRedo = useCallback(() => {
    if (historyPointerRef.current < historyRef.current.length - 1) {
      historyPointerRef.current += 1;
      const nextState = historyRef.current[historyPointerRef.current];
      isUndoRedoActionRef.current = true;
      setBlocks(nextState);
    }
  }, []);

  const updateBlock = useCallback((id: string, updates: Partial<Block>) => {
    if (readOnly) return;
    setBlocks((prev) => prev.map((b) => (b.id === id ? { ...b, ...updates } : b)));
  }, [readOnly]);

  const addBlock = useCallback((afterId: string, type: BlockType = "text", content: string = "") => {
    if (readOnly) return;
    setBlocks((prev) => {
      const newBlock = { id: generateId(), type, content };
      const index = prev.findIndex((b) => b.id === afterId);
      const next = [...prev];
      next.splice(index + 1, 0, newBlock);
      setFocusedId(newBlock.id);
      return next;
    });
  }, [readOnly]);

  const removeBlock = useCallback((id: string) => {
    if (readOnly) return;
    setBlocks((prev) => {
      if (prev.length <= 1) return [{ id: generateId(), type: "text", content: "" }];
      const index = prev.findIndex((b) => b.id === id);
      const prevBlock = prev[index - 1];
      const next = prev.filter((b) => b.id !== id);
      if (prevBlock) setFocusedId(prevBlock.id);
      return next;
    });
  }, [readOnly]);

  const moveFocus = useCallback((id: string, direction: number) => {
    const index = blocks.findIndex((b) => b.id === id);
    const nextIndex = index + direction;
    if (nextIndex >= 0 && nextIndex < blocks.length) {
      setFocusedId(blocks[nextIndex].id);
    }
  }, [blocks]);

  const changeBlockType = useCallback((id: string, type: BlockType, newContent?: string) => {
    if (readOnly) return;
    setBlocks((prev) => prev.map((b) => {
      if (b.id === id) {
        let content = newContent !== undefined ? newContent : b.content;
        if (newContent === undefined && content.endsWith("/")) {
          content = content.slice(0, -1);
        }
        return { ...b, type, content };
      }
      return b;
    }));
    setShowSlashMenu(null);
  }, [readOnly]);

  const pasteBlocks = useCallback((
    afterId: string,
    pastedText: string,
    selectionStart: number,
    selectionEnd: number
  ) => {
    if (readOnly) return;

    const normalizedText = normalizePastedText(pastedText);

    setBlocks((prev) => {
      const index = prev.findIndex((b) => b.id === afterId);
      if (index === -1) return prev;

      const currentBlock = prev[index];
      const leftText = currentBlock.content.slice(0, selectionStart);
      const rightText = currentBlock.content.slice(selectionEnd);

      // Special handling for code block to avoid parsing contents as separate block types
      if (currentBlock.type === "code") {
        const next = [...prev];
        next[index] = {
          ...currentBlock,
          content: leftText + normalizedText + rightText,
        };
        return next;
      }

      // Temporarily build a block with left content to serialize correctly (handles list item prefixes etc.)
      const tempLeftBlock: Block = {
        ...currentBlock,
        content: leftText,
      };

      let prefixMarkdown = "";
      if (leftText || currentBlock.type !== "text") {
        prefixMarkdown = serializeBlocksToMarkdown([tempLeftBlock]);
      }

      let suffixMarkdown = "";
      if (rightText) {
        suffixMarkdown = serializeBlocksToMarkdown([{
          id: generateId(),
          type: "text",
          content: rightText,
        }]);
      }

      // Combine local markdown
      let localMarkdown = prefixMarkdown;
      if (prefixMarkdown && !prefixMarkdown.endsWith("\n") && normalizedText) {
        localMarkdown += normalizedText;
      } else {
        localMarkdown += normalizedText;
      }

      if (rightText) {
        if (!localMarkdown.endsWith("\n")) {
          localMarkdown += "\n";
        }
        localMarkdown += suffixMarkdown;
      }

      const localBlocks = parseMarkdownToBlocks(localMarkdown, allowTasks);
      if (localBlocks.length === 0) return prev;

      const next = [...prev];
      next.splice(index, 1, ...localBlocks);

      // Focus the last inserted/merged block
      const lastInsertedBlock = localBlocks[localBlocks.length - 1];
      setFocusedId(lastInsertedBlock.id);

      return next;
    });
  }, [readOnly, allowTasks]);

  const containerRef = useRef<HTMLDivElement>(null);

  const selectAll = useCallback(() => {
    setFocusedId(null);
    setTimeout(() => {
      if (containerRef.current) {
        const range = document.createRange();
        range.selectNodeContents(containerRef.current);
        const selection = window.getSelection();
        if (selection) {
          selection.removeAllRanges();
          selection.addRange(range);
        }
      }
    }, 0);
  }, []);

  useEffect(() => {
    const handleWindowKeyDown = (e: KeyboardEvent) => {
      if (readOnly) return;
      
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed) return;

      if (containerRef.current && !containerRef.current.contains(selection.anchorNode)) return;

      if (e.key === "Backspace" || e.key === "Delete") {
        e.preventDefault();
        const newId = generateId();
        setBlocks([{ id: newId, type: "text", content: "" }]);
        setFocusedId(newId);
        selection.removeAllRanges();
        return;
      }

      const isCharacter = e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey;
      if (isCharacter) {
        e.preventDefault();
        const newId = generateId();
        setBlocks([{ id: newId, type: "text", content: e.key }]);
        setFocusedId(newId);
        selection.removeAllRanges();
      }
    };

    const handleCopyCut = (e: ClipboardEvent) => {
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed) return;

      if (containerRef.current && containerRef.current.contains(selection.anchorNode)) {
        e.preventDefault();
        const serialized = serializeBlocksToMarkdown(blocks);
        e.clipboardData?.setData("text/plain", serialized);
        
        if (e.type === "cut" && !readOnly) {
          const newId = generateId();
          setBlocks([{ id: newId, type: "text", content: "" }]);
          setFocusedId(newId);
          selection.removeAllRanges();
        }
      }
    };

    window.addEventListener("keydown", handleWindowKeyDown);
    window.addEventListener("copy", handleCopyCut);
    window.addEventListener("cut", handleCopyCut);
    return () => {
      window.removeEventListener("keydown", handleWindowKeyDown);
      window.removeEventListener("copy", handleCopyCut);
      window.removeEventListener("cut", handleCopyCut);
    };
  }, [blocks, readOnly]);

  return (
    <div 
      className="flex flex-col border border-white/10 rounded-2xl bg-black/40 overflow-hidden shadow-inner group-focus-within:border-blue-500/50 transition-all duration-300"
      style={{ minHeight: height }}
    >
      <div 
        ref={containerRef}
        className="flex-1 overflow-y-auto p-6 space-y-1 custom-scrollbar cursor-text"
        onClick={(e) => {
          if (e.target === e.currentTarget && blocks.length > 0) {
            const lastBlock = blocks[blocks.length - 1];
            setFocusedId(lastBlock.id);
          }
        }}
      >
        {blocks.map((block) => (
          <BlockNode
            key={block.id}
            block={block}
            isFocused={focusedId === block.id}
            isLocked={readOnly}
            showSlashMenu={showSlashMenu === block.id}
            onFocus={() => setFocusedId(block.id)}
            updateBlock={updateBlock}
            addBlock={addBlock}
            removeBlock={removeBlock}
            moveFocus={moveFocus}
            setShowSlashMenu={setShowSlashMenu}
            changeBlockType={changeBlockType}
            performUndo={performUndo}
            performRedo={performRedo}
            allowTasks={allowTasks}
            pasteBlocks={pasteBlocks}
            selectAll={selectAll}
          />
        ))}
        {blocks.length === 0 && (
          <div 
            className="h-full flex items-center justify-center text-gray-600 italic cursor-text"
            onClick={() => addBlock("", "text")}
          >
            {placeholder}
          </div>
        )}
      </div>
      
      <div className="px-4 py-2 bg-white/5 border-t border-white/5 flex items-center justify-between text-[10px] text-gray-500 font-mono">
        <div className="flex gap-4">
          <span>{blocks.length} blocks</span>
          <span>{value.length} chars</span>
        </div>
        <div className="flex gap-2 opacity-50 hover:opacity-100 transition-opacity">
          <span>↑/↓ navigate</span>
          <span>/ commands</span>
        </div>
      </div>
    </div>
  );
}
