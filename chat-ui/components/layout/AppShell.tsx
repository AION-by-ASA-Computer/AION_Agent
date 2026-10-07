"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";
import { useIsLgUp } from "@/lib/hooks/use-breakpoint";
import {
  DOCK_WIDTH_SERVER_SNAPSHOT,
  clampDock,
  persistDockWidth,
  readDockWidth,
  subscribeDockWidth,
} from "@/lib/layout/dock-width-store";

export function AppShell({
  sidebar,
  header,
  children,
  dock,
  isDockOpen = false,
  isSidebarOpen = true,
  onCloseDock,
  onCloseSidebar,
  className,
}: {
  sidebar: React.ReactNode;
  header: React.ReactNode;
  children: React.ReactNode;
  dock?: React.ReactNode;
  isDockOpen?: boolean;
  isSidebarOpen?: boolean;
  onCloseDock?: () => void;
  onCloseSidebar?: () => void;
  className?: string;
}) {
  const isLgUp = useIsLgUp();
  const dockW = useSyncExternalStore(
    subscribeDockWidth,
    readDockWidth,
    () => DOCK_WIDTH_SERVER_SNAPSHOT,
  );
  const [resizing, setResizing] = useState(false);
  const [dragWidth, setDragWidth] = useState<number | null>(null);
  const startRef = useRef({ x: 0, w: DOCK_WIDTH_SERVER_SNAPSHOT });
  const dragWidthRef = useRef<number | null>(null);

  const activeW = dragWidth !== null ? dragWidth : dockW;

  const showMobileSidebar = isSidebarOpen && !isLgUp;
  const showMobileDock = isDockOpen && !isLgUp && Boolean(dock);

  useEffect(() => {
    if (!showMobileSidebar && !showMobileDock) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [showMobileSidebar, showMobileDock]);

  useEffect(() => {
    if (!resizing) return;
    function move(e: MouseEvent) {
      const min = 320;
      const max = Math.min(800, window.innerWidth * 0.6);
      const dx = startRef.current.x - e.clientX;
      const newWidth = Math.min(Math.max(startRef.current.w + dx, min), max);
      dragWidthRef.current = newWidth;
      setDragWidth(newWidth);
    }
    function up() {
      setResizing(false);
      const finalWidth = dragWidthRef.current;
      if (finalWidth !== null) {
        persistDockWidth(finalWidth);
      }
      dragWidthRef.current = null;
      setDragWidth(null);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    }
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, [resizing]);

  const startDrag = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      startRef.current = { x: e.clientX, w: dockW };
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      setResizing(true);
    },
    [dockW],
  );

  return (
    <div
      className={cn(
        "grid h-[100dvh] w-full overflow-hidden bg-background text-foreground",
        "grid-cols-[minmax(0,1fr)]",
        "lg:grid-cols-[auto_minmax(0,1fr)_auto]",
        className,
      )}
    >
      {/* Mobile sidebar backdrop */}
      {showMobileSidebar ? (
        <button
          type="button"
          aria-label="Chiudi menu conversazioni"
          className="fixed inset-0 z-40 bg-background/70 backdrop-blur-[2px] lg:hidden"
          onClick={onCloseSidebar}
        />
      ) : null}

      {/* Mobile dock backdrop */}
      {showMobileDock ? (
        <button
          type="button"
          aria-label="Chiudi pannello laterale"
          className="fixed inset-0 z-40 bg-background/70 backdrop-blur-[2px] lg:hidden"
          onClick={onCloseDock}
        />
      ) : null}

      <aside
        style={isLgUp && isSidebarOpen ? { width: "var(--sidebar-w)" } : undefined}
        className={cn(
          "flex min-h-0 flex-col overflow-hidden text-sidebar-foreground backdrop-blur-2xl",
          "transition-[transform,width,opacity,border-color] duration-300 ease-out",
          // Mobile / tablet: floating drawer
          "fixed inset-y-3 left-3 z-50 w-[min(88vw,calc(var(--sidebar-w)+1rem))] rounded-3xl border border-black/[0.08] bg-sidebar/90 shadow-2xl dark:border-white/[0.09] dark:bg-sidebar/80",
          // Desktop: floating sidebar
          "lg:static lg:z-auto lg:my-3 lg:ml-3 lg:h-[calc(100dvh-1.5rem)] lg:rounded-3xl lg:border lg:border-black/[0.08] lg:bg-sidebar/80 lg:shadow-xl dark:lg:border-white/[0.09] dark:lg:bg-sidebar/55",
          isSidebarOpen
            ? "translate-x-0 opacity-100"
            : "-translate-x-full opacity-0 pointer-events-none lg:pointer-events-auto",
          // Desktop collapsed rail
          !isSidebarOpen && "lg:w-16 lg:translate-x-0 lg:opacity-100",
        )}
      >
        {sidebar}
      </aside>

      <div className="flex min-h-0 min-w-0 flex-col bg-background">
        {header}
        <div className="grid min-h-0 min-w-0 flex-1 grid-rows-[minmax(0,1fr)]">{children}</div>
      </div>

      {dock ? (
        <>
          {/* Desktop dock column */}
          <div
            className={cn(
              "relative hidden min-h-0 min-w-0 lg:my-3 lg:h-[calc(100dvh-1.5rem)] lg:rounded-3xl lg:border lg:border-black/[0.08] dark:lg:border-white/[0.09] lg:bg-card/50 lg:backdrop-blur-xl lg:shadow-xl lg:block",
              !resizing && "transition-[width,opacity,margin,transform] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
              "overflow-hidden",
              isDockOpen && dock ? "lg:mr-3 opacity-100 translate-x-0" : "pointer-events-none !border-0 opacity-0 lg:mr-0 translate-x-4",
            )}
            style={{ width: isDockOpen && dock ? activeW : 0 }}
          >
            {isDockOpen && dock ? (
              <button
                type="button"
                aria-label="Ridimensiona pannello destro"
                onMouseDown={startDrag}
                className="focus-ring absolute left-0 top-0 z-20 h-full w-2 -translate-x-1/2 cursor-col-resize bg-transparent hover:bg-primary/40 transition-colors"
              />
            ) : null}
            <div
              className="flex h-full min-h-0 min-w-0 flex-col"
              style={{ width: activeW }}
            >
              {dock}
            </div>
          </div>

          {/* Mobile dock sheet */}
          <div
            className={cn(
              "fixed inset-y-3 right-3 z-50 flex w-[min(calc(100vw-1.5rem),28rem)] flex-col rounded-3xl border border-black/[0.08] dark:border-white/[0.09] bg-card/90 shadow-2xl backdrop-blur-2xl transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] lg:hidden",
              isDockOpen ? "translate-x-0" : "pointer-events-none translate-x-[calc(100%+1.5rem)]",
            )}
            aria-hidden={!isDockOpen}
          >
            {isDockOpen ? (
              <button
                type="button"
                aria-label="Chiudi pannello"
                onClick={onCloseDock}
                className="focus-ring absolute right-3 top-3 z-20 rounded-xl border border-border/60 bg-background/80 p-1.5 text-muted-foreground hover:text-foreground"
              >
                <X className="size-4" aria-hidden />
              </button>
            ) : null}
            <div className="flex h-full min-h-0 min-w-0 flex-col pt-10">{dock}</div>
          </div>
        </>
      ) : null}
    </div>
  );
}
