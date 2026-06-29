/** Console diagnostics for Deep Research (filter DevTools: "AION Research"). */

const PREFIX = "[AION Research]";

export function researchLog(message: string, data?: unknown): void {
  if (typeof window === "undefined") return;
  if (data !== undefined) console.info(PREFIX, message, data);
  else console.info(PREFIX, message);
}

export function researchWarn(message: string, data?: unknown): void {
  if (typeof window === "undefined") return;
  if (data !== undefined) console.warn(PREFIX, message, data);
  else console.warn(PREFIX, message);
}

export function researchError(message: string, data?: unknown): void {
  if (typeof window === "undefined") return;
  if (data !== undefined) console.error(PREFIX, message, data);
  else console.error(PREFIX, message);
}
