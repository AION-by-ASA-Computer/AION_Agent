"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useConversationThreads } from "./use-conversation-threads";

export type SidebarPanel = "threads" | "tunings";
export type SidebarTuningsTab = "runtime" | "presets";

export const TUNINGS_TABS: SidebarTuningsTab[] = ["runtime", "presets"];

export function parseTuningsTab(raw: string | null | undefined): SidebarTuningsTab {
  const v = (raw || "").trim().toLowerCase();
  if (v === "presets" || v === "preset") return "presets";
  return "runtime";
}

/** Returns null when the query refers to full-page settings (profile, appearance, …). */
export function parseTuningsTabFromQuery(raw: string | null | undefined): SidebarTuningsTab | null {
  const v = (raw || "").trim().toLowerCase();
  if (!v) return null;
  if (v === "presets" || v === "preset") return "presets";
  if (v === "runtime" || v === "tuning" || v === "tunings") return "runtime";
  if (
    v === "profile" ||
    v === "appearance" ||
    v === "security" ||
    v === "instructions" ||
    v === "user-md" ||
    v === "account"
  ) {
    return null;
  }
  return "runtime";
}

export type ShellActions = ReturnType<typeof useConversationThreads> & {
  setHeader: (node: ReactNode) => void;
  setDock: (node: ReactNode) => void;
  setDockOpen: (open: boolean) => void;
  clearChrome: () => void;
  toggleSidebar: () => void;
  closeSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  setDockCloseHandler: (handler: (() => void) | null) => void;
  invokeDockClose: () => void;
  sidebarPanel: SidebarPanel;
  tuningsTab: SidebarTuningsTab;
  openTunings: (tab?: SidebarTuningsTab) => void;
  closeTunings: () => void;
  setTuningsTab: (tab: SidebarTuningsTab) => void;
};

export type ShellChromeState = {
  header: ReactNode;
  dock: ReactNode;
  dockOpen: boolean;
};

const ShellActionsContext = createContext<ShellActions | null>(null);
const ShellChromeContext = createContext<ShellChromeState | null>(null);
const ShellSidebarOpenContext = createContext<boolean>(false);

export function ShellProvider({ children }: { children: ReactNode }) {
  const threads = useConversationThreads();
  const [header, setHeaderState] = useState<ReactNode>(null);
  const [dock, setDockState] = useState<ReactNode>(null);
  const [dockOpen, setDockOpenState] = useState(false);
  const [sidebarOpen, setSidebarOpenState] = useState(false);
  const [sidebarPanel, setSidebarPanel] = useState<SidebarPanel>("threads");
  const [tuningsTab, setTuningsTabState] = useState<SidebarTuningsTab>("runtime");
  const dockCloseRef = useRef<(() => void) | null>(null);

  const setDockCloseHandler = useCallback((handler: (() => void) | null) => {
    dockCloseRef.current = handler;
  }, []);

  const invokeDockClose = useCallback(() => {
    dockCloseRef.current?.();
  }, []);

  const setHeader = useCallback((node: ReactNode) => setHeaderState(node), []);
  const setDock = useCallback((node: ReactNode) => setDockState(node), []);
  const setDockOpen = useCallback((open: boolean) => setDockOpenState(open), []);

  const clearChrome = useCallback(() => {
    setHeaderState(null);
    setDockState(null);
    setDockOpenState(false);
  }, []);

  const toggleSidebar = useCallback(() => {
    setSidebarOpenState((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("aion-chat-sidebar-open", next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const closeSidebar = useCallback(() => {
    setSidebarOpenState(false);
    try {
      localStorage.setItem("aion-chat-sidebar-open", "0");
    } catch {
      /* ignore */
    }
  }, []);

  const setSidebarOpen = useCallback((open: boolean) => {
    setSidebarOpenState(open);
    try {
      localStorage.setItem("aion-chat-sidebar-open", open ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, []);

  const openTunings = useCallback((tab?: SidebarTuningsTab) => {
    if (tab) setTuningsTabState(tab);
    setSidebarPanel("tunings");
    setSidebarOpenState(true);
    try {
      localStorage.setItem("aion-chat-sidebar-open", "1");
    } catch {
      /* ignore */
    }
  }, []);

  const closeTunings = useCallback(() => {
    setSidebarPanel("threads");
  }, []);

  const setTuningsTab = useCallback((tab: SidebarTuningsTab) => {
    setTuningsTabState(tab);
    setSidebarPanel("tunings");
  }, []);

  const actions = useMemo<ShellActions>(
    () => ({
      ...threads,
      setHeader,
      setDock,
      setDockOpen,
      clearChrome,
      toggleSidebar,
      closeSidebar,
      setSidebarOpen,
      setDockCloseHandler,
      invokeDockClose,
      sidebarPanel,
      tuningsTab,
      openTunings,
      closeTunings,
      setTuningsTab,
    }),
    [
      threads,
      setHeader,
      setDock,
      setDockOpen,
      clearChrome,
      toggleSidebar,
      closeSidebar,
      setSidebarOpen,
      setDockCloseHandler,
      invokeDockClose,
      sidebarPanel,
      tuningsTab,
      openTunings,
      closeTunings,
      setTuningsTab,
    ],
  );

  const chrome = useMemo<ShellChromeState>(
    () => ({ header, dock, dockOpen }),
    [header, dock, dockOpen],
  );

  return (
    <ShellActionsContext.Provider value={actions}>
      <ShellChromeContext.Provider value={chrome}>
        <ShellSidebarOpenContext.Provider value={sidebarOpen}>
          {children}
        </ShellSidebarOpenContext.Provider>
      </ShellChromeContext.Provider>
    </ShellActionsContext.Provider>
  );
}

export function useShellActions(): ShellActions {
  const ctx = useContext(ShellActionsContext);
  if (!ctx) throw new Error("useShellActions must be used within ShellProvider");
  return ctx;
}

export function useShellChrome(): ShellChromeState {
  const ctx = useContext(ShellChromeContext);
  if (!ctx) throw new Error("useShellChrome must be used within ShellProvider");
  return ctx;
}

export function useSidebarOpen(): boolean {
  return useContext(ShellSidebarOpenContext);
}

/** @deprecated Prefer granular hooks to avoid re-render loops. */
export function useShellLayout(): ShellChromeState & { sidebarOpen: boolean } {
  return { ...useShellChrome(), sidebarOpen: useSidebarOpen() };
}

export function useShell(): ShellActions & ShellChromeState & { sidebarOpen: boolean } {
  return { ...useShellActions(), ...useShellChrome(), sidebarOpen: useSidebarOpen() };
}

export function useShellOptional(): (ShellActions & ShellChromeState & { sidebarOpen: boolean }) | null {
  const actions = useContext(ShellActionsContext);
  const chrome = useContext(ShellChromeContext);
  const sidebarOpen = useContext(ShellSidebarOpenContext);
  if (!actions || !chrome) return null;
  return { ...actions, ...chrome, sidebarOpen };
}
