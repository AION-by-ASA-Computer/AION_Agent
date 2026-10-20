"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

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
