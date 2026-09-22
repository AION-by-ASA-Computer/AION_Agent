"use client";

import { useState } from "react";
import { Check, Edit2, X, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

interface PiiReviewData {
  original_prompt?: string;
  censored_prompt?: string;
  pii_review_token?: string;
}

export function PiiReviewArtifactBlock({
  content,
  onAction,
  assistantMessageId,
}: {
  content: string;
  onAction?: (action: "confirm" | "reject", finalPrompt?: string, token?: string, assistantMessageId?: string) => void;
  assistantMessageId?: string;
}) {
  const t = useT();
  const [isEditing, setIsEditing] = useState(false);
  const [editedPrompt, setEditedPrompt] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  const cleanPrompt = (text?: string) => {
    if (!text) return "";
    let result = text;

    // Rimuove la memoria di sessione
    result = result.replace(/\[session_memory\][\s\S]*?(?=--- runtime context|\[System instruction|$)/i, "");

    // Rimuove il contesto di runtime interno
    result = result.replace(/--- runtime context[\s\S]*?--- end runtime context ---\n?/g, "");

    // Rimuove le system instruction (di solito finiscono prima dell'ultimo \n\n)
    result = result.replace(/\[System instruction[\s\S]*?(?=\n\n|$)/g, "");

    // Pulizia di frasi residue note delle skill
    result = result.replace(/Only after loading any required missing skills, proceed to execute the task\.\n*/g, "");

    return result.trim();
  };

  let data: PiiReviewData = {};
  try {
    data = JSON.parse(content || "{}");
  } catch (e) {
    // potentially streaming or malformed, ignore
  }

  const handleConfirm = () => {
    console.log("[PiiReviewArtifactBlock] confirming with token:", data.pii_review_token);
    onAction?.("confirm", isEditing ? editedPrompt : cleanPrompt(data.censored_prompt), data.pii_review_token, assistantMessageId);
    setConfirmed(true);
  };

  const startEdit = () => {
    setEditedPrompt(cleanPrompt(data.censored_prompt) || "");
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
          {isEditing ? (
            <textarea
              className="mt-1 w-full p-2 bg-background border border-rose-500/40 rounded-lg focus-ring min-h-[100px]"
              value={editedPrompt}
              onChange={(e) => setEditedPrompt(e.target.value)}
            />
          ) : (
            <p className="mt-1 p-2 rounded-lg whitespace-pre-wrap text-foreground font-medium">
              {cleanPrompt(data.censored_prompt) || "In attesa..."}
            </p>
          )}
        </div>

        {!confirmed && (
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
        )}
      </div>
    </div>
  );
}
