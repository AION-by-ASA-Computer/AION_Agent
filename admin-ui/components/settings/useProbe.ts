"use client";

import { useCallback, useState } from "react";
import type { LlmProbeResponse } from "@/lib/llm-probe";

/** State shared by the three "test connection and discover models" flows. */
export function useProbe(savedModel = "") {
  const [probing, setProbing] = useState(false);
  const [result, setResult] = useState<LlmProbeResponse | null>(null);
  const [latency, setLatency] = useState<number | null>(null);
  const [tested, setTested] = useState(!!savedModel);
  const [ids, setIds] = useState<string[]>(savedModel ? [savedModel] : []);
  const [manual, setManual] = useState(!!savedModel);

  const reset = useCallback(() => {
    setResult(null);
    setLatency(null);
    setTested(false);
    setIds([]);
    setManual(false);
  }, []);

  /** Mark an already-saved model as known so its form opens without a new probe. */
  const seed = useCallback((model: string) => {
    setResult(null);
    setLatency(null);
    setTested(!!model);
    setIds(model ? [model] : []);
    setManual(!!model);
  }, []);

  return { probing, setProbing, result, setResult, latency, setLatency, tested, setTested, ids, setIds, manual, setManual, reset, seed };
}

export type Probe = ReturnType<typeof useProbe>;
