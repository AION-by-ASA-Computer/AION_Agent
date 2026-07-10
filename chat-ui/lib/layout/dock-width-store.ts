/** Dock panel width persisted in localStorage; external store for useSyncExternalStore. */

const DOCK_STORAGE_KEY = "aion-chat-dock-w";
export const DOCK_WIDTH_SERVER_SNAPSHOT = 420;

export function clampDock(n: number, min: number, max: number) {
  return Math.min(Math.max(n, min), max);
}

export function readDockWidth(): number {
  if (typeof window === "undefined") return DOCK_WIDTH_SERVER_SNAPSHOT;
  try {
    const raw = localStorage.getItem(DOCK_STORAGE_KEY);
    if (!raw) return DOCK_WIDTH_SERVER_SNAPSHOT;
    const parsed = parseInt(raw, 10);
    if (Number.isNaN(parsed)) return DOCK_WIDTH_SERVER_SNAPSHOT;
    const max = Math.min(800, window.innerWidth * 0.6);
    return clampDock(parsed, 320, max);
  } catch {
    return DOCK_WIDTH_SERVER_SNAPSHOT;
  }
}

const dockWidthListeners = new Set<() => void>();

export function subscribeDockWidth(listener: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const onStorage = (e: StorageEvent) => {
    if (e.key !== DOCK_STORAGE_KEY && e.key !== null) return;
    listener();
  };
  window.addEventListener("storage", onStorage);
  dockWidthListeners.add(listener);
  return () => {
    window.removeEventListener("storage", onStorage);
    dockWidthListeners.delete(listener);
  };
}

function notifyDockWidthListeners(): void {
  dockWidthListeners.forEach((l) => {
    try {
      l();
    } catch {
      /* ignore listener failures (e.g. stale HMR subscriptions) */
    }
  });
}

export function persistDockWidth(w: number): void {
  try {
    localStorage.setItem(DOCK_STORAGE_KEY, String(Math.round(w)));
  } catch {
    /* ignore */
  }
  notifyDockWidthListeners();
}
