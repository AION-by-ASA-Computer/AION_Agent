"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { fetchResearchLibrary, reportUrl, type ResearchLibraryItem } from "@/lib/api/research";
import { apiBase } from "@/lib/config";

export default function ResearchLibraryPage() {
  const [items, setItems] = useState<ResearchLibraryItem[]>([]);
  const [userId, setUserId] = useState("default");
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const uid = localStorage.getItem("aion_user_id") || "default";
    const tok = localStorage.getItem("aion_chat_token");
    setUserId(uid);
    setToken(tok);
    void fetchResearchLibrary(uid, tok, { limit: 100 }).then(setItems);
  }, []);

  return (
    <main className="mx-auto max-w-3xl p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Research Library</h1>
        <Link href="/" className="text-sm text-violet-400 hover:underline">
          Back to chat
        </Link>
      </div>
      <p className="mb-4 text-sm text-muted-foreground">
        Saved deep research reports ({apiBase()})
      </p>
      <ul className="space-y-3">
        {items.map((it) => (
          <li key={it.id} className="flex items-center justify-between rounded-lg border border-border p-4">
            <div>
              <p className="font-medium">{it.query || it.id}</p>
              <p className="text-xs text-muted-foreground">
                {it.source_count ?? 0} sources · {it.status}
              </p>
            </div>
            <a
              href={reportUrl(it.id)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm text-violet-400 hover:underline"
            >
              Open <ExternalLink className="h-4 w-4" />
            </a>
          </li>
        ))}
        {items.length === 0 && (
          <li className="text-sm text-muted-foreground">No research saved yet.</li>
        )}
      </ul>
    </main>
  );
}
