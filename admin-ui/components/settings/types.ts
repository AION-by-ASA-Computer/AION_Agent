export type Settings = Record<string, string>;
export type T = (key: string, vars?: Record<string, string | number>) => string;
export type Notify = (message: string, variant?: "success" | "error" | "warning" | "info") => void;

/** What the page hands to every section. */
export type SectionCtx = {
  t: T;
  settings: Settings;
  set: (key: string, value: string) => void;
  setMany: (patch: Settings) => void;
  notify: Notify;
  /** Backend asked for a restart: show the overlay and wait for health. */
  onRestart: () => void;
};

export const K = "admin_settings";
