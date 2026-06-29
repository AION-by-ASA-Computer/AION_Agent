"use client";

import { useEffect, useState } from "react";

export function AgentDbPanel({ userId, tableHint }: { userId: string; tableHint?: string | null }) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const q = new URLSearchParams({ userId });
        if (tableHint) q.set("table", tableHint);
        const r = await fetch(`/api/agent-db-embed?${q.toString()}`);
        const j = (await r.json()) as { url?: string; error?: string };
        if (!cancelled) {
          if (j.url) setUrl(j.url);
          else setErr(j.error || "embed failed");
        }
      } catch (e) {
        if (!cancelled) setErr(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId, tableHint]);

  if (err)
    return (
      <div className="p-6 text-sm text-destructive font-medium" role="alert">
        Si è verificato un errore: {err}
      </div>
    );
  if (!url) return (
    <div className="flex h-32 items-center justify-center p-4">
       <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <span className="size-3 animate-pulse rounded-full bg-primary/40"></span>
          Caricamento editor DB…
       </div>
    </div>
  );
  return (
    <div className="h-full flex flex-col p-4 pb-0">
      <iframe
        title="Agent DB"
        src={url}
        className="h-full min-h-[320px] w-full flex-1 rounded-tl-xl rounded-tr-xl border-x border-t border-border/50 bg-background shadow-inner"
      />
    </div>
  );
}
