"use client";

import { useState } from "react";
import { Check, Edit2, X, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

interface PiiReviewData {
  original_prompt?: string;
  censored_prompt?: string;
}

export function PiiReviewArtifactBlock({
  content,
  onAction,
}: {
  content: string;
  onAction?: (action: "confirm" | "reject", finalPrompt?: string) => void;
}) {
  const t = useT();
  const [isEditing, setIsEditing] = useState(false);
  const [editedPrompt, setEditedPrompt] = useState("");
  
  let data: PiiReviewData = {};
  try {
    data = JSON.parse(content || "{}");
  } catch (e) {
    // potentially streaming or malformed, ignore
  }

  const handleConfirm = () => {
    onAction?.("confirm", isEditing ? editedPrompt : data.censored_prompt);
  };

  const startEdit = () => {
    setEditedPrompt(data.censored_prompt || "");
    setIsEditing(true);
  };

  return (
    <div className="my-3 rounded-xl border border-rose-500/30 bg-rose-500/5 overflow-hidden shadow-sm">
      <div className="flex items-center gap-2 bg-rose-500/10 px-4 py-2 border-b border-rose-500/20">
        <ShieldAlert className="w-4 h-4 text-rose-600 dark:text-rose-400" />
        <h3 className="font-semibold text-sm text-rose-800 dark:text-rose-300">
          Revisione Sicurezza (PII)
        </h3>
      </div>
      
      <div className="p-4 text-sm space-y-4">
        <div>
          <span className="font-semibold text-muted-foreground text-xs uppercase tracking-wider">Testo Originale</span>
          <p className="mt-1 p-2 bg-muted/40 rounded-lg whitespace-pre-wrap opacity-70">
            {data.original_prompt || "In attesa..."}
          </p>
        </div>
        
        <div>
          <span className="font-semibold text-rose-700 dark:text-rose-400 text-xs uppercase tracking-wider">Testo Censurato</span>
          {isEditing ? (
            <textarea
              className="mt-1 w-full p-2 bg-background border border-rose-500/40 rounded-lg focus-ring min-h-[100px]"
              value={editedPrompt}
              onChange={(e) => setEditedPrompt(e.target.value)}
            />
          ) : (
            <p className="mt-1 p-2 bg-rose-500/10 border border-rose-500/20 rounded-lg whitespace-pre-wrap text-foreground font-medium">
              {data.censored_prompt || "In attesa..."}
            </p>
          )}
        </div>
        
        <div className="flex items-center justify-end gap-2 pt-2 border-t border-border/50">
          {isEditing ? (
             <button
              onClick={() => setIsEditing(false)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted rounded-lg transition-colors"
            >
              <X className="w-3.5 h-3.5" />
              Annulla
            </button>
          ) : (
             <button
              onClick={startEdit}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted rounded-lg transition-colors"
            >
              <Edit2 className="w-3.5 h-3.5" />
              Modifica
            </button>
          )}
         
          <button
            onClick={handleConfirm}
            className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-bold text-white bg-rose-600 hover:bg-rose-500 rounded-lg transition-colors"
          >
            <Check className="w-3.5 h-3.5" />
            Conferma ed Invia
          </button>
        </div>
      </div>
    </div>
  );
}
