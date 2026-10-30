"use client";

import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { MessageBranchInfo } from "@/lib/api/aion";

interface BranchNavigatorProps {
  branches: MessageBranchInfo;
  onNavigateBranch: (targetConversationId: string) => void;
  disabled?: boolean;
  className?: string;
}

export function BranchNavigator({
  branches,
  onNavigateBranch,
  disabled = false,
  className = "",
}: BranchNavigatorProps) {
  const { total, current_index, prev_branch_conversation_id, next_branch_conversation_id } = branches;

  if (total <= 1) return null;

  const canGoPrev = !disabled && Boolean(prev_branch_conversation_id);
  const canGoNext = !disabled && Boolean(next_branch_conversation_id);

  return (
    <div
      className={`inline-flex items-center gap-1 rounded-full border border-border/50 bg-background/70 px-2 py-0.5 text-xs text-muted-foreground backdrop-blur-md shadow-sm transition-colors hover:border-border/80 ${className}`}
      role="group"
      aria-label={`Ramo di conversazione ${current_index} di ${total}`}
    >
      <button
        type="button"
        disabled={!canGoPrev}
        onClick={(e) => {
          e.stopPropagation();
          if (prev_branch_conversation_id) {
            onNavigateBranch(prev_branch_conversation_id);
          }
        }}
        className="rounded p-0.5 hover:bg-muted/60 hover:text-foreground disabled:opacity-30 disabled:pointer-events-none transition-colors"
        title="Passa al ramo precedente"
        aria-label="Passa al ramo precedente"
      >
        <ChevronLeft size={13} className="shrink-0" />
      </button>

      <span className="font-mono text-[11px] font-medium tracking-tight px-1 select-none text-foreground/90">
        {current_index} / {total}
      </span>

      <button
        type="button"
        disabled={!canGoNext}
        onClick={(e) => {
          e.stopPropagation();
          if (next_branch_conversation_id) {
            onNavigateBranch(next_branch_conversation_id);
          }
        }}
        className="rounded p-0.5 hover:bg-muted/60 hover:text-foreground disabled:opacity-30 disabled:pointer-events-none transition-colors"
        title="Passa al ramo successivo"
        aria-label="Passa al ramo successivo"
      >
        <ChevronRight size={13} className="shrink-0" />
      </button>
    </div>
  );
}
