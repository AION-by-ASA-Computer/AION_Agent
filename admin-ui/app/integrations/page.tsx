"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

/** Deprecato: policy utenti MCP è nel MCP Hub unificato. */
export default function IntegrationsRedirectPage() {
  const router = useRouter();
  const params = useSearchParams();

  useEffect(() => {
    const focus = params.get("focus") || "integrations";
    router.replace(`/hub?focus=${encodeURIComponent(focus)}`);
  }, [router, params]);

  return <p className="p-8 text-gray-400 text-sm">Reindirizzamento a MCP Hub…</p>;
}
