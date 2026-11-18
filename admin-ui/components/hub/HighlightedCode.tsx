"use client";

/**
 * Minimal, dependency-free syntax highlighting for the snippets of the custom MCP
 * developer guide (CustomMcpGuideDialog): aion-mcp.yaml, server.py, terminal
 * commands and the folder tree. It only needs to make short, known snippets
 * readable (comments, keys, strings, keywords), not to parse arbitrary code, so a
 * few regular expressions are enough and no highlighting library is shipped.
 *
 * Colours come in light/dark pairs (`dark:` follows `data-theme="dark"`, see
 * app/globals.css) so the code stays readable with both themes.
 */

import { Fragment, type ReactNode } from "react";

export type CodeLanguage = "yaml" | "python" | "bash" | "tree";

const C = {
  comment: "text-muted-foreground italic",
  key: "text-sky-700 dark:text-sky-300",
  string: "text-emerald-700 dark:text-emerald-300",
  keyword: "text-violet-700 dark:text-violet-300 font-medium",
  literal: "text-amber-700 dark:text-amber-300",
  decorator: "text-pink-700 dark:text-pink-300",
  func: "text-blue-700 dark:text-blue-300",
  punct: "text-muted-foreground",
  folder: "text-sky-700 dark:text-sky-300 font-medium",
} as const;

type Token = { text: string; cls?: string };

const span = (tokens: Token[]): ReactNode =>
  tokens.map((tk, i) => (tk.cls ? <span key={i} className={tk.cls}>{tk.text}</span> : <Fragment key={i}>{tk.text}</Fragment>));

/** Scan `text` with a global regex whose capture groups map to `classes`; unmatched text stays plain. */
function scan(text: string, re: RegExp, classes: (string | undefined)[]): Token[] {
  const out: Token[] = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    const start = m.index ?? 0;
    if (start > last) out.push({ text: text.slice(last, start) });
    const group = m.slice(1).findIndex((g) => g !== undefined);
    out.push({ text: m[0], cls: classes[group] });
    last = start + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}

const PY_KEYWORDS =
  "def|class|return|if|elif|else|import|from|as|for|while|in|not|and|or|is|async|await|with|try|except|finally|raise|lambda|pass|yield|global";
// Order matters: comments and strings first so keywords inside them are not coloured.
const PY_RE = new RegExp(
  [
    "(#[^\\n]*)", // comment
    '([rbuf]{0,2}"""[\\s\\S]*?"""|[rbuf]{0,2}\'\'\'[\\s\\S]*?\'\'\')', // triple-quoted string
    '([rbuf]{0,2}"(?:\\\\.|[^"\\\\\\n])*"|[rbuf]{0,2}\'(?:\\\\.|[^\'\\\\\\n])*\')', // string
    "(@[\\w.]+)", // decorator
    "(?<=\\bdef )(\\w+)", // function name
    `\\b(${PY_KEYWORDS})\\b`, // keyword
    "\\b(True|False|None|\\d+(?:\\.\\d+)?)\\b", // literal
  ].join("|"),
  "g",
);

function highlightPython(code: string): Token[] {
  return scan(code, PY_RE, [C.comment, C.string, C.string, C.decorator, C.func, C.keyword, C.literal]);
}

/** YAML value after `key:` — comment, quoted/plain string, number/bool. */
function yamlValue(value: string): Token[] {
  const hash = value.search(/(^|\s)#/);
  const body = hash >= 0 ? value.slice(0, hash) : value;
  const comment = hash >= 0 ? value.slice(hash) : "";
  const trimmed = body.trim();
  const out: Token[] = [];
  if (trimmed) {
    const lead = body.slice(0, body.indexOf(trimmed));
    const tail = body.slice(body.indexOf(trimmed) + trimmed.length);
    const isLiteral = /^(true|false|null|~|-?\d+(\.\d+)*)$/i.test(trimmed);
    out.push({ text: lead }, { text: trimmed, cls: isLiteral ? C.literal : C.string }, { text: tail });
  } else {
    out.push({ text: body });
  }
  if (comment) out.push({ text: comment, cls: C.comment });
  return out;
}

function highlightYamlLine(line: string): Token[] {
  if (/^\s*#/.test(line)) return [{ text: line, cls: C.comment }];
  const m = line.match(/^(\s*)(- )?([A-Za-z_][\w-]*)(:)(.*)$/);
  if (m) {
    return [
      { text: m[1] },
      ...(m[2] ? [{ text: m[2], cls: C.punct }] : []),
      { text: m[3], cls: C.key },
      { text: m[4], cls: C.punct },
      ...yamlValue(m[5]),
    ];
  }
  const item = line.match(/^(\s*)(- )(.*)$/);
  if (item) return [{ text: item[1] }, { text: item[2], cls: C.punct }, ...yamlValue(item[3])];
  return [{ text: line }];
}

function highlightBashLine(line: string): Token[] {
  if (/^\s*#/.test(line)) return [{ text: line, cls: C.comment }];
  const [first, ...rest] = line.split(/(\s+)/);
  return [
    { text: first, cls: C.func },
    ...rest.map((part) => ({ text: part, cls: part.startsWith("-") ? C.keyword : undefined })),
  ];
}

function highlightTreeLine(line: string): Token[] {
  const hash = line.indexOf("#");
  const body = hash >= 0 ? line.slice(0, hash) : line;
  const m = body.match(/^([│├└─\s]*)(.*)$/) ?? ["", "", body];
  const name = m[2];
  return [
    { text: m[1], cls: C.punct },
    { text: name, cls: name.trim().endsWith("/") ? C.folder : C.string },
    ...(hash >= 0 ? [{ text: line.slice(hash), cls: C.comment }] : []),
  ];
}

const LINE_HIGHLIGHTERS: Record<Exclude<CodeLanguage, "python">, (line: string) => Token[]> = {
  yaml: highlightYamlLine,
  bash: highlightBashLine,
  tree: highlightTreeLine,
};

/** Coloured `<code>` content for `code` in `language`. */
export function HighlightedCode({ code, language }: { code: string; language: CodeLanguage }) {
  if (language === "python") return <code>{span(highlightPython(code))}</code>;
  const highlight = LINE_HIGHLIGHTERS[language];
  const lines = code.split("\n");
  return (
    <code>
      {lines.map((line, i) => (
        <Fragment key={i}>
          {span(highlight(line))}
          {i < lines.length - 1 ? "\n" : null}
        </Fragment>
      ))}
    </code>
  );
}
