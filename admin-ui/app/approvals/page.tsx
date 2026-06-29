"use client";

import React from "react";

export default function ApprovalsPage() {
  return (
    <div className="p-8 text-gray-500 italic">Visualizzazione Approvals non disponibile.</div>
  );
}

/*
import { useState } from "react";
import { ClipboardList, Info } from "lucide-react";
import { apiBase } from "@/lib/api";
import { PageToast, type ToastState } from "@/components/PageToast";

export default function OriginalApprovalsPage() {
  const [toast, setToast] = useState<ToastState>(null);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-8 pb-8">
      <PageToast toast={toast} onDismiss={() => setToast(null)} />
      <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-amber-500/30 bg-amber-600/15">
            <ClipboardList className="h-6 w-6 text-amber-300" />
          </div>
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-white">Tool approvals</h1>
            <p className="mt-1 max-w-2xl text-sm text-gray-400">
              Le regole persistenti (`approval_rules`) e l&apos;endpoint{" "}
              <code className="text-gray-500">POST /v1/chat/approval</code> saranno esposti quando{" "}
              <code className="text-gray-500">AION_UNIFIED_DB=1</code> (default). Oggi:{" "}
              <code className="text-gray-500">AION_APPROVAL_ENABLED</code> +{" "}
              <code className="text-gray-500">AION_APPROVAL_CRITICAL_TOOLS</code> nel backend.
            </p>
          </div>
        </div>
      </header>
      <div className="glass-card flex gap-3 rounded-xl border border-[#333] bg-[#111] p-4 text-sm text-gray-400">
        <Info className="h-5 w-5 shrink-0 text-amber-400" />
        <span>
          API base: <code className="text-gray-300">{apiBase()}</code>
        </span>
      </div>
    </div>
  );
}
*/
