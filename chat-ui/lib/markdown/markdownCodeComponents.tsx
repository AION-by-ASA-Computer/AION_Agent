"use client";

import type { Components } from "react-markdown";
import { MarkdownCodeBlock } from "@/components/chat/MarkdownCodeBlock";
import { MermaidBlock } from "@/components/chat/MermaidBlock";

type MarkdownCodeOptions = {
  streaming?: boolean;
};

export function markdownCodeComponents(opts: MarkdownCodeOptions = {}): Partial<Components> {
  return {
    pre: ({ children }) => <>{children}</>,
    code: ({ className, children, ...props }) => {
      const match = /language-(\w+)/.exec(className || "");
      const lang = match ? match[1] : "";
      const isInline = !match;
      const codeContent = String(children).replace(/\n$/, "");

      if (isInline) {
        return (
          <code
            className="rounded-md bg-muted/80 px-1.5 py-0.5 font-mono text-[0.88em] text-foreground ring-1 ring-border/50"
            {...props}
          >
            {children}
          </code>
        );
      }

      if (lang === "mermaid") {
        return <MermaidBlock code={codeContent} isStreaming={Boolean(opts.streaming)} />;
      }

      return (
        <MarkdownCodeBlock language={lang || "text"} code={codeContent} streaming={opts.streaming} />
      );
    },
  };
}
