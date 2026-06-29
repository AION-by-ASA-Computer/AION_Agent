"use client";

import { useEffect, useRef, useState, useId, memo } from "react";
import { createPortal } from "react-dom";
import { Copy, Check, Eye, Code, Maximize2, Minimize2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/cn";

interface MermaidBlockProps {
  code: string;
  isStreaming?: boolean;
}

export const MermaidBlock = memo(function MermaidBlock({ code, isStreaming = false }: MermaidBlockProps) {
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"chart" | "code">("chart");
  const [copied, setCopied] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [fullscreen, setFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const [portalTarget, setPortalTarget] = useState<Element | null>(null);

  useEffect(() => {
    if (fullscreen && typeof window !== "undefined") {
      setPortalTarget(document.getElementById("chat-pane") || document.body);
    } else {
      setPortalTarget(null);
    }
  }, [fullscreen]);

  // Create an SSR-safe ID and sanitize it for DOM/CSS selectors
  const baseId = useId();
  const elementId = "mermaid-" + baseId.replace(/[^a-zA-Z0-9]/g, "");

  // Detect theme updates via MutationObserver on html element
  useEffect(() => {
    if (typeof window === "undefined") return;
    const currentTheme = document.documentElement.dataset.theme === "light" ? "light" : "dark";
    setTheme(currentTheme);

    const observer = new MutationObserver(() => {
      const nextTheme = document.documentElement.dataset.theme === "light" ? "light" : "dark";
      setTheme(nextTheme);
    });

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    return () => observer.disconnect();
  }, []);

  // Render diagram when code, theme, or isStreaming changes (with debounce during stream)
  useEffect(() => {
    let active = true;
    let timerId: NodeJS.Timeout | null = null;

    const renderDiagram = async () => {
      if (!code.trim()) return;

      try {
        setError(null);
        // Dynamically import mermaid to avoid SSR issues
        const { default: mermaid } = await import("mermaid");

        mermaid.initialize({
          startOnLoad: false,
          theme: theme === "light" ? "default" : "dark",
          securityLevel: "loose",
          fontFamily: "Arial, sans-serif",
          themeVariables: {
            fontFamily: "Arial, sans-serif",
          },
          flowchart: { htmlLabels: true, useMaxWidth: false },
          sequence: { useMaxWidth: false },
          gantt: { useMaxWidth: false },
          journey: { useMaxWidth: false },
          class: { useMaxWidth: false },
          state: { useMaxWidth: false },
          er: { useMaxWidth: false },
        });

        // 1. Parse code first to catch errors cleanly without breaking DOM
        try {
          await mermaid.parse(code);
        } catch (parseErr: any) {
          // If parse fails, throw to skip rendering and handle in catch block
          throw parseErr;
        }

        // 2. Render SVG string
        const { svg: renderedSvg } = await mermaid.render(elementId + "-svg", code);

        if (active) {
          setSvg(renderedSvg);
        }
      } catch (err: any) {
        if (active) {
          // Clean up any error state elements created by mermaid in the DOM body
          const badElement = document.getElementById(elementId + "-svg");
          if (badElement) badElement.remove();
          const badBindElement = document.getElementById("d" + elementId + "-svg");
          if (badBindElement) badBindElement.remove();

          // Only set error and log to console if not streaming
          if (!isStreaming) {
            console.error("Mermaid parsing/rendering error:", err);
            setError(err.message || String(err));
          }
        }
      }
    };

    if (isStreaming) {
      // Debounce renders during active stream to keep UI responsive
      timerId = setTimeout(() => {
        void renderDiagram();
      }, 250);
    } else {
      void renderDiagram();
    }

    return () => {
      active = false;
      if (timerId) {
        clearTimeout(timerId);
      }
    };
  }, [code, theme, elementId, isStreaming]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy mermaid code:", err);
    }
  };

  const fullscreenOverlay = (
    <div
      id={elementId + "-fullscreen"}
      className="absolute inset-0 z-50 flex flex-col bg-background/95 backdrop-blur-md p-6 shadow-2xl"
    >
      <style>{`
        #${elementId}-fullscreen foreignObject {
          overflow: visible !important;
        }
        #${elementId}-fullscreen .node label,
        #${elementId}-fullscreen .node td,
        #${elementId}-fullscreen .node span,
        #${elementId}-fullscreen .node div,
        #${elementId}-fullscreen .nodeText,
        #${elementId}-fullscreen .nodeLabel,
        #${elementId}-fullscreen .label {
          font-family: Arial, sans-serif !important;
        }
      `}</style>
      
      {/* Fullscreen Header */}
      <div className="flex items-center justify-between border-b border-border/60 pb-3 mb-4 text-xs select-none">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-foreground/80 text-sm">Diagramma Mermaid (Schermo Intero)</span>
        </div>
        <div className="flex items-center gap-1.5">
          {/* Copy Button */}
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1 rounded-lg border border-border/40 bg-background/50 px-3 py-1.5 text-muted-foreground hover:text-foreground hover:bg-muted/80 transition-colors"
          >
            {copied ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
            <span>{copied ? "Copiato" : "Copia Codice"}</span>
          </button>

          {/* Close Button */}
          <button
            type="button"
            onClick={() => setFullscreen(false)}
            className="inline-flex items-center gap-1 rounded-lg border border-border/40 bg-primary px-3 py-1.5 text-primary-foreground hover:bg-primary/95 transition-colors font-medium"
          >
            <Minimize2 size={12} />
            <span>Chiudi</span>
          </button>
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-auto flex flex-col items-center justify-start p-4 bg-muted/5 rounded-xl border border-border/40">
        {svg ? (
          <div
            className="w-full overflow-x-auto [&_svg]:max-w-none [&_svg]:h-auto [&_svg]:mx-auto"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        ) : (
          <div className="text-xs text-muted-foreground animate-pulse">
            Generazione diagramma...
          </div>
        )}
      </div>
    </div>
  );

  return (
    <>
      <div
        id={elementId}
        className="my-4 overflow-hidden rounded-xl border border-border bg-card/45 shadow-sm transition-all duration-200"
      >
      <style>{`
        #${elementId} foreignObject {
          overflow: visible !important;
        }
        #${elementId} .node label,
        #${elementId} .node td,
        #${elementId} .node span,
        #${elementId} .node div,
        #${elementId} .nodeText,
        #${elementId} .nodeLabel,
        #${elementId} .label {
          font-family: Arial, sans-serif !important;
        }
      `}</style>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/60 bg-muted/30 px-3.5 py-2 text-xs select-none">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-foreground/80">Diagramma Mermaid</span>
          {error && (
            <span className="flex items-center gap-1 rounded bg-destructive/10 px-1.5 py-0.5 text-[10px] font-medium text-destructive">
              <AlertTriangle size={10} />
              <span>Errore</span>
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {/* Mode Toggle Button */}
          {!error && (
            <button
              type="button"
              onClick={() => setMode(mode === "chart" ? "code" : "chart")}
              className="inline-flex items-center gap-1 rounded-lg border border-border/40 bg-background/50 px-2 py-1 text-muted-foreground hover:text-foreground hover:bg-muted/80 transition-colors"
              title={mode === "chart" ? "Mostra codice sorgente" : "Mostra grafico"}
            >
              {mode === "chart" ? (
                <>
                  <Code size={12} />
                  <span>Codice</span>
                </>
              ) : (
                <>
                  <Eye size={12} />
                  <span>Grafico</span>
                </>
              )}
            </button>
          )}

          {/* Copy Button */}
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1 rounded-lg border border-border/40 bg-background/50 px-2 py-1 text-muted-foreground hover:text-foreground hover:bg-muted/80 transition-colors"
          >
            {copied ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
            <span>{copied ? "Copiato" : "Copia"}</span>
          </button>

          {/* Fullscreen Button */}
          <button
            type="button"
            onClick={() => setFullscreen(!fullscreen)}
            className="inline-flex items-center justify-center rounded-lg border border-border/40 bg-background/50 p-1 text-muted-foreground hover:text-foreground hover:bg-muted/80 transition-colors"
            title={fullscreen ? "Chiudi schermo intero" : "Schermo intero"}
          >
            {fullscreen ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
          </button>
        </div>
      </div>

      {/* Content Area */}
      <div
        ref={containerRef}
        className={cn(
          "relative overflow-auto p-4 flex flex-col items-center justify-start min-h-[150px] bg-muted/5",
          fullscreen ? "flex-1 p-8" : "max-h-[500px]"
        )}
      >
        {mode === "chart" && !error ? (
          svg ? (
            <div
              className="w-full overflow-x-auto [&_svg]:max-w-none [&_svg]:h-auto [&_svg]:mx-auto"
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          ) : (
            <div className="text-xs text-muted-foreground animate-pulse py-8">
              Generazione diagramma...
            </div>
          )
        ) : (
          /* Code View / Error View */
          <div className="w-full flex flex-col gap-2">
            {error && (
              <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-xs text-destructive">
                <span className="font-semibold block mb-1">Errore di rendering:</span>
                <pre className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed">
                  {error}
                </pre>
              </div>
            )}
            <pre className="m-0 overflow-x-auto rounded-lg border border-border/50 bg-background/50 p-3 text-xs font-mono text-foreground/90">
              <code>{code}</code>
            </pre>
          </div>
        )}
      </div>
    </div>
    {fullscreen && portalTarget && createPortal(fullscreenOverlay, portalTarget)}
  </>
  );
});
