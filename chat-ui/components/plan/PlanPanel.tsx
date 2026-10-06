"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Sparkles, Workflow, ArrowRight, Lightbulb, Compass, ListTodo, Plus } from "lucide-react";
import type { ChatChunk } from "@/lib/sse/types";
import { PlanDockPanel } from "@/components/dock/PlanDockPanel";
import { StreamingContentPreview } from "@/components/dock/StreamingContentPreview";
import type { PlanExecutionProgressState } from "@/hooks/use-plan-execution-progress";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

type PlanPanelPhase = "drafting" | "review" | "executing" | "done" | "error";

type PlanPendingChunk = ChatChunk & { type: "orchestration_plan_pending" };

function syntheticExecutionChunk(planId: string): PlanPendingChunk {
  return {
    type: "orchestration_plan_pending",
    plan_id: planId,
    plan: {},
    plan_markdown: "",
    todos: [],
    annotations: {},
    revision: 1,
    goal: "Execution plan",
  };
}

export function PlanPanel({
  chunk,
  apiBaseUrl,
  sessionId,
  remountKey,
  userId,
  profileName,
  token,
  planStreaming,
  planLiveMarkdown,
  adoptRunId,
  adoptPlanId,
  executionProgress,
  selectedTaskId,
  onAdoptHandled,
  onPlanApproved,
  onPlanRejected,
  onFinalSummary,
  onTaskSelect,
  onPromptSuggestion,
}: {
  chunk: PlanPendingChunk | null;
  apiBaseUrl: string;
  sessionId: string;
  remountKey: number;
  userId: string;
  profileName: string;
  token?: string | null;
  planStreaming?: boolean;
  planLiveMarkdown?: string;
  adoptRunId?: string | null;
  adoptPlanId?: string | null;
  executionProgress?: PlanExecutionProgressState | null;
  selectedTaskId?: string | null;
  onAdoptHandled?: () => void;
  onPlanApproved?: (runId: string, planId: string) => void;
  onPlanRejected?: (planId?: string) => void;
  onFinalSummary?: (summary: string, planId: string, runId?: string) => void;
  onTaskSelect?: (taskId: string | null) => void;
  onPromptSuggestion?: (text: string) => void;
}) {
  const t = useT();
  const [executionRunId, setExecutionRunId] = useState<string | null>(null);
  const [executionPlanId, setExecutionPlanId] = useState<string | null>(null);

  const handleApproved = useCallback(
    (runId: string, planId: string) => {
      setExecutionRunId(runId);
      setExecutionPlanId(planId);
      onPlanApproved?.(runId, planId);
    },
    [onPlanApproved],
  );

  const handleRejected = useCallback(
    (planId?: string) => {
      setExecutionRunId(null);
      setExecutionPlanId(null);
      onPlanRejected?.(planId);
    },
    [onPlanRejected],
  );

  useEffect(() => {
    if (!adoptRunId) {
      setExecutionRunId(null);
      setExecutionPlanId(null);
    }
  }, [adoptRunId]);

  const effectiveRunId = adoptRunId || executionRunId;
  const effectivePlanId = adoptPlanId || executionPlanId;
  const phase: PlanPanelPhase = useMemo(() => {
    if (effectiveRunId) return "executing";
    if (planStreaming) return "drafting";
    if (chunk) return "review";
    return "review";
  }, [chunk, effectiveRunId, planStreaming]);

  const effectiveChunk = useMemo((): PlanPendingChunk | null => {
    if (chunk) return chunk;
    const pid = (effectivePlanId || "").trim();
    if (pid && effectiveRunId) return syntheticExecutionChunk(pid);
    return null;
  }, [chunk, effectivePlanId, effectiveRunId]);

  const [showInfo, setShowInfo] = useState(false);

  if (planStreaming && chunk) {
    return (
      <StreamingContentPreview
        title={String(chunk.goal || chunk.plan_id || "Plan")}
        content={planLiveMarkdown || ""}
        streaming
        kind="plan"
      />
    );
  }

  if (!effectiveChunk) {
    return (
      <div className="relative flex h-full flex-col justify-between p-4 overflow-y-auto custom-scrollbar animate-in fade-in-0 duration-200">
        {/* Centered Hero Section */}
        <div className="flex flex-col items-center text-center my-auto py-4">
          <div className="relative mb-3 flex size-14 items-center justify-center rounded-2xl bg-gradient-to-br from-orange-500 to-amber-600 text-white shadow-lg shadow-orange-500/25 ring-4 ring-orange-500/10">
            <Workflow size={28} />
          </div>

          <div className="flex items-center gap-2">
            <h3 className="text-base font-bold text-foreground">Modalità Pianificazione</h3>
            <span className="rounded-full border border-orange-500/30 bg-orange-500/15 px-2.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wider text-orange-600 dark:text-orange-400">
              Orchestrazione
            </span>
            <button
              type="button"
              onClick={() => setShowInfo((v) => !v)}
              className="focus-ring rounded-full p-1 text-muted-foreground hover:bg-orange-500/15 hover:text-orange-500 transition-colors"
              title="Informazioni su Modalità Pianificazione"
              aria-label="Informazioni su Modalità Pianificazione"
            >
              <Lightbulb size={16} className={showInfo ? "text-orange-500" : "text-muted-foreground"} />
            </button>
          </div>

          <p className="mt-2 text-sm leading-relaxed text-muted-foreground max-w-sm">
            L&apos;agente scompone obiettivi complessi in task sequenziali e paralleli, verificando ogni avanzamento prima di procedere.
          </p>

          {/* Suggestion Cards */}
          <div className="mt-6 w-full space-y-2 text-left">
            <div className="flex items-center justify-between px-1">
              <span className="text-[0.75em] font-bold uppercase tracking-wider text-muted-foreground/80">
                Idee per iniziare un piano
              </span>
            </div>

            <div className="grid grid-cols-1 gap-2">
              {[
                {
                  title: "Analisi strategica & Architettura",
                  desc: "Definisci requisiti, vincoli e roadmap tecnica per un nuovo modulo.",
                  prompt: "Crea un piano dettagliato per l'analisi dei requisiti e la progettazione architetturale del nuovo progetto.",
                },
                {
                  title: "Refactoring & Miglioramento Codice",
                  desc: "Pianifica pulizia del codice, refactoring modulare e test di regressione.",
                  prompt: "Elabora un piano di refactoring del codice per migliorare la manutenibilità e le performance.",
                },
                {
                  title: "Collaudo, Testing & Deployment",
                  desc: "Struttura una suite di test end-to-end e pipeline di rilascio.",
                  prompt: "Crea un piano operativo per implementare test automatici e validare il rilascio.",
                },
              ].map((item, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onPromptSuggestion?.(item.prompt)}
                  className="group relative flex flex-col rounded-2xl border border-black/[0.06] dark:border-white/[0.08] bg-card/60 dark:bg-card/30 p-3.5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-orange-500/40 hover:bg-card/90 hover:shadow-md"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-foreground group-hover:text-orange-500 transition-colors flex items-center gap-1.5">
                      <Plus size={14} className="text-orange-500 opacity-70 group-hover:opacity-100 transition-opacity" />
                      {item.title}
                    </span>
                    <ArrowRight size={13} className="text-muted-foreground opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all text-orange-500" />
                  </div>
                  <p className="mt-1 text-[0.78em] leading-relaxed text-muted-foreground">
                    {item.desc}
                  </p>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Info Popover / Modal overlay */}
        {showInfo && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs animate-in fade-in duration-150">
            <div className="w-full max-w-sm rounded-2xl border border-orange-500/30 bg-background/95 p-5 shadow-2xl backdrop-blur-xl animate-in zoom-in-95 duration-150">
              <div className="flex items-center justify-between border-b border-border/50 pb-3">
                <div className="flex items-center gap-2">
                  <div className="flex size-7 items-center justify-center rounded-lg bg-orange-500/15 text-orange-500">
                    <Workflow size={16} />
                  </div>
                  <h4 className="text-sm font-bold text-foreground">Come attivare un piano</h4>
                </div>
                <button
                  type="button"
                  onClick={() => setShowInfo(false)}
                  className="focus-ring rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  <Plus size={16} className="rotate-45" />
                </button>
              </div>

              <div className="mt-3.5 space-y-3 text-xs leading-relaxed text-muted-foreground">
                <div className="flex items-start gap-2.5">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-orange-500/15 text-orange-600 dark:text-orange-400 font-bold text-[11px]">1</span>
                  <p>
                    Attiva la modalità <strong className="text-foreground">Plan</strong> dal selettore agente nella barra di scrittura in basso.
                  </p>
                </div>
                <div className="flex items-start gap-2.5">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-orange-500/15 text-orange-600 dark:text-orange-400 font-bold text-[11px]">2</span>
                  <div>
                    <p>Oppure chiedi direttamente in chat:</p>
                    <span className="mt-1 block rounded-lg border border-orange-500/20 bg-orange-500/5 p-2 font-mono text-[11px] text-foreground">
                      «Crea un piano di esecuzione per [il tuo obiettivo]»
                    </span>
                  </div>
                </div>
                <div className="flex items-start gap-2.5">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-orange-500/15 text-orange-600 dark:text-orange-400 font-bold text-[11px]">3</span>
                  <p>
                    L&apos;agente strutturerà il piano a tappe e ti permetterà di revisionarlo prima di avviarlo in totale sicurezza.
                  </p>
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-border/50 text-right">
                <button
                  type="button"
                  onClick={() => setShowInfo(false)}
                  className="rounded-xl bg-orange-500 px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-orange-600 transition-colors"
                >
                  Ho capito
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <PlanDockPanel
      chunk={effectiveChunk}
      apiBaseUrl={apiBaseUrl}
      sessionId={sessionId}
      remountKey={remountKey}
      userId={userId}
      profileName={profileName}
      authToken={token}
      executionRunId={phase === "executing" ? effectiveRunId : null}
      executionProgress={executionProgress}
      selectedTaskId={selectedTaskId}
      onPlanApproved={handleApproved}
      onPlanRejected={handleRejected}
      onFinalSummary={onFinalSummary}
      onExecutionAdoptHandled={onAdoptHandled}
      onTaskSelect={onTaskSelect}
    />
  );
}
