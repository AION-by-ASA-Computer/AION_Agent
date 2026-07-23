"use client";

import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { FileText, ListTodo } from "lucide-react";

import type { TurnSegment } from "@/lib/sse/types";
import { useT } from "@/lib/i18n/use-t";
import type { ToolsViewMode } from "@/components/chat/WebResearchViews";
import { AssistantToolStepBlock } from "@/components/chat/WebResearchViews";
import { CodeArtifactBlock } from "@/components/chat/CodeArtifactBlock";
import { ReasoningDisclosure } from "@/components/chat/ReasoningDisclosure";
import { ShimmerText } from "@/components/chat/ShimmerText";
import { StatusProgressCard } from "@/components/chat/StatusProgressCard";
import { artifactLanguage } from "@/lib/artifacts";
import { isScriptLikeTitle } from "@/lib/sse/filePreviewTools";
import { sessionDownloadUrl } from "@/lib/api/aion";
import { markdownCodeComponents } from "@/lib/markdown/markdownCodeComponents";

type Props = {
  segments: TurnSegment[];
  toolsView: ToolsViewMode;
  streaming?: boolean;
  conversationId?: string;
  token?: string | null;
  isPlanArtifact?: (art: { identifier: string; type?: string; title?: string }, buffer: string) => boolean;
  renderMarkdownLink?: React.ComponentProps<typeof ReactMarkdown>["components"] extends infer C
  ? C extends { a?: infer A }
  ? A
  : never
  : never;
  formatTextWithCitations?: (text: string, messageId?: string) => string;
  messageId?: string;
};

export function TurnTimeline({
  segments,
  toolsView,
  streaming = false,
  conversationId,
  token,
  isPlanArtifact,
  renderMarkdownLink,
  formatTextWithCitations = (t) => t,
  messageId,
}: Props) {
  const t = useT();
  if (!segments.length) return null;

  const lastSeg = segments[segments.length - 1];

  return (
    <div className="space-y-2.5">
      {segments.map((seg, idx) => {
        const isLast = idx === segments.length - 1;
        if (seg.kind === "generating") {
          const Icon = seg.target === "plan" ? ListTodo : FileText;
          const scriptLike = isScriptLikeTitle(seg.title);
          const label =
            seg.target === "plan"
              ? t("chat.generating.plan")
              : scriptLike && seg.title?.trim()
                ? t("chat.generating.script_named", { title: seg.title })
                : scriptLike
                  ? t("chat.generating.script")
                  : seg.title?.trim()
                    ? t("chat.generating.document_named", { title: seg.title })
                    : t("chat.generating.document");
          return (
            <StatusProgressCard
              key={seg.id}
              icon={Icon}
              title={label}
              subtitle={t("chat.tool.waiting")}
            />
          );
        }
        if (seg.kind === "status") {
          const warn = seg.tone === "warning";
          return (
            <div
              key={seg.id}
              className={
                warn
                  ? "rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-900 dark:text-amber-100"
                  : "rounded-lg border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground"
              }
              role="status"
              aria-live="polite"
            >
              {streaming && isLast ? (
                <ShimmerText className="text-xs">{seg.content}</ShimmerText>
              ) : (
                seg.content
              )}
            </div>
          );
        }
        if (seg.kind === "reasoning") {
          const reasoningStreaming = streaming && isLast && seg.kind === "reasoning";
          return (
            <ReasoningDisclosure
              key={seg.id}
              content={seg.content}
              streaming={reasoningStreaming}
            />
          );
        }
        if (seg.kind === "tool") {
          if (seg.name === "thinking") {
            if (seg.status === "running") {
              return (
                <div
                  key={seg.id}
                  className="rounded-lg border border-border/50 bg-muted/25 px-3 py-2 text-xs"
                  role="status"
                  aria-live="polite"
                >
                  <ShimmerText className="text-xs">
                    {t("chat.agent_status.working")}
                  </ShimmerText>
                </div>
              );
            }
            return null;
          }

          if ((seg as any).masked === "minimum") {
            return (
              <AssistantToolStepBlock
                key={seg.id}
                name={seg.name}
                input={seg.input}
                output={seg.output}
                isError={seg.isError}
                status={seg.status}
                toolsView={toolsView}
                tokens_in={seg.tokens_in}
                tokens_out={seg.tokens_out}
                masked={(seg as any).masked}
              />
            );
          }

          if (toolsView === "hidden") {
            if (seg.status === "running") {
              return (
                <div
                  key={seg.id}
                  className="rounded-lg border border-border/50 bg-muted/25 px-3 py-2 text-xs"
                  role="status"
                  aria-live="polite"
                >
                  <ShimmerText className="text-xs">
                    {t("chat.tool.running", { name: seg.name })}
                  </ShimmerText>
                </div>
              );
            }
            return null;
          }

          return (
            <AssistantToolStepBlock
              key={seg.id}
              name={seg.name}
              input={seg.input}
              output={seg.output}
              isError={seg.isError}
              status={seg.status}
              toolsView={toolsView}
              tokens_in={seg.tokens_in}
              tokens_out={seg.tokens_out}
            />
          );
        }
        if (seg.kind === "artifact") {
          const planCheck = isPlanArtifact
            ? isPlanArtifact(
              { identifier: seg.id, type: seg.artType, title: seg.title },
              seg.buffer,
            )
            : false;
          if (planCheck) return null;
          const artifactStreaming =
            streaming && isLast && !seg.savedPath;
          return (
            <CodeArtifactBlock
              key={seg.id}
              id={`artifact-${seg.id}`}
              title={seg.title || seg.id}
              language={artifactLanguage(seg.artType, seg.savedPath || "")}
              code={seg.buffer}
              savedPath={seg.savedPath}
              downloadUrl={
                seg.savedPath && conversationId && token
                  ? sessionDownloadUrl(conversationId, seg.savedPath, token)
                  : undefined
              }
              execution={seg.execution}
              defaultOpen={!planCheck && !seg.savedPath}
              streaming={artifactStreaming}
            />
          );
        }
        if (seg.kind === "text" && seg.content.trim()) {
          return (
            <div key={seg.id} className="prose-chat">
              <TextSegment
                content={seg.content.trimStart()}
                streaming={streaming}
                isLast={isLast}
                renderMarkdownLink={renderMarkdownLink}
                formatTextWithCitations={(txt: string) => formatTextWithCitations(txt, messageId)}
              />
            </div>
          );
        }
        return null;
      })}
      {streaming &&
        segments.length > 0 &&
        lastSeg?.kind === "reasoning" &&
        !segments.some((s) => s.kind === "tool" && s.status === "running") ? (
        <ShimmerText className="mt-1 text-sm">{t("chat.agent_status.working")}</ShimmerText>
      ) : null}
    </div>
  );
}

/** Shimmer label while the agent has not started visible output yet. */
export function AgentWorkingShimmer({ label }: { label: string }) {
  return <ShimmerText className="py-2 leading-relaxed">{label}</ShimmerText>;
}

const TextSegment = memo(function TextSegment({
  content,
  streaming,
  isLast,
  renderMarkdownLink,
  formatTextWithCitations,
}: {
  content: string;
  streaming: boolean;
  isLast: boolean;
  renderMarkdownLink: any;
  formatTextWithCitations: any;
}) {
  const components = useMemo(() => ({
    table: ({ node: _node, ...props }: any) => (
      <div className="table-wrapper">
        <table {...props} />
      </div>
    ),
    ...markdownCodeComponents({ streaming: streaming && isLast }),
    ...(renderMarkdownLink ? { a: renderMarkdownLink } : {}),
  }), [streaming, isLast, renderMarkdownLink]);

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      disallowedElements={["script"]}
      unwrapDisallowed
      components={components}
    >
      {formatTextWithCitations(content)}
    </ReactMarkdown>
  );
});
