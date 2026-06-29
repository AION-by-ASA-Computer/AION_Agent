"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, RotateCcw } from "lucide-react";

import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

// IMPORTANTE: workerSrc va configurato nel file dove si usano i componenti (react-pdf docs)
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

// Costanti zoom — definite fuori dal componente per evitare re-creazioni
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3.0;
const ZOOM_STEP = 0.25;
const ZOOM_DEFAULT = 1.0;

interface KhubPdfViewerProps {
  src: string;
}

export function KhubPdfViewer({ src }: KhubPdfViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [pageNumber, setPageNumber] = useState<number>(1);
  const [containerWidth, setContainerWidth] = useState<number>(0);
  const [zoomScale, setZoomScale] = useState<number>(ZOOM_DEFAULT);

  const containerRef = useRef<HTMLDivElement>(null);

  // ResizeObserver per la larghezza dinamica del container
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        // padding orizzontale 24px per lato → sottrai 48px
        setContainerWidth(Math.max(0, entry.contentRect.width - 48));
      }
    });

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Reset alla pagina 1 e allo zoom default quando cambia il documento
  useEffect(() => {
    setPageNumber(1);
    setNumPages(0);
    setZoomScale(ZOOM_DEFAULT);
  }, [src]);

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
    setPageNumber(1);
  }, []);

  // --- Navigazione pagine ---
  const goToPrevPage = useCallback(() => {
    setPageNumber((prev) => Math.max(1, prev - 1));
  }, []);

  const goToNextPage = useCallback(() => {
    setPageNumber((prev) => Math.min(numPages, prev + 1));
  }, [numPages]);

  const handlePageInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = parseInt(e.target.value, 10);
      if (!isNaN(val) && val >= 1 && val <= numPages) {
        setPageNumber(val);
      }
    },
    [numPages]
  );

  // --- Zoom ---
  const zoomIn = useCallback(() => {
    setZoomScale((prev) => Math.min(ZOOM_MAX, parseFloat((prev + ZOOM_STEP).toFixed(2))));
  }, []);

  const zoomOut = useCallback(() => {
    setZoomScale((prev) => Math.max(ZOOM_MIN, parseFloat((prev - ZOOM_STEP).toFixed(2))));
  }, []);

  const zoomReset = useCallback(() => {
    setZoomScale(ZOOM_DEFAULT);
  }, []);

  // Keyboard shortcuts: Ctrl/Cmd + = (zoom in), − (zoom out), 0 (reset)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      if (e.key === "=" || e.key === "+") {
        e.preventDefault();
        zoomIn();
      } else if (e.key === "-") {
        e.preventDefault();
        zoomOut();
      } else if (e.key === "0") {
        e.preventDefault();
        zoomReset();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [zoomIn, zoomOut, zoomReset]);

  return (
    <div className="flex flex-col h-full w-full min-h-0">

      {/* Toolbar: navigazione pagine + separatore + controlli zoom */}
      {numPages > 0 && (
        <div className="shrink-0 flex items-center justify-center gap-2 border-t border-border bg-card/80 py-2 px-4 select-none">

          {/* Navigazione pagine */}
          <button
            type="button"
            onClick={goToPrevPage}
            disabled={pageNumber <= 1}
            className="flex items-center justify-center w-7 h-7 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            aria-label="Pagina precedente"
          >
            <ChevronLeft size={16} />
          </button>

          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <input
              type="number"
              min={1}
              max={numPages}
              value={pageNumber}
              onChange={handlePageInput}
              className="w-10 rounded-md border border-border bg-background px-1.5 py-0.5 text-center text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
              aria-label="Numero pagina"
            />
            <span>/</span>
            <span className="font-medium text-foreground">{numPages}</span>
          </div>

          <button
            type="button"
            onClick={goToNextPage}
            disabled={pageNumber >= numPages}
            className="flex items-center justify-center w-7 h-7 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            aria-label="Pagina successiva"
          >
            <ChevronRight size={16} />
          </button>

          {/* Separatore */}
          <div className="w-px h-5 bg-border mx-1" aria-hidden />

          {/* Zoom out */}
          <button
            type="button"
            onClick={zoomOut}
            disabled={zoomScale <= ZOOM_MIN}
            className="flex items-center justify-center w-7 h-7 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            aria-label="Riduci zoom (Ctrl −)"
            title="Riduci zoom (Ctrl −)"
          >
            <ZoomOut size={14} />
          </button>

          {/* Percentuale zoom — cliccabile per reset a 100% */}
          <button
            type="button"
            onClick={zoomReset}
            className="min-w-[3rem] rounded-md border border-border bg-background px-2 py-0.5 text-center text-xs text-foreground hover:bg-muted transition-colors"
            aria-label="Reset zoom 100% (Ctrl 0)"
            title="Reset zoom 100% (Ctrl 0)"
          >
            {Math.round(zoomScale * 100)}%
          </button>

          {/* Zoom in */}
          <button
            type="button"
            onClick={zoomIn}
            disabled={zoomScale >= ZOOM_MAX}
            className="flex items-center justify-center w-7 h-7 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            aria-label="Aumenta zoom (Ctrl +)"
            title="Aumenta zoom (Ctrl +)"
          >
            <ZoomIn size={14} />
          </button>

          {/* Reset zoom — icona dedicata */}
          <button
            type="button"
            onClick={zoomReset}
            disabled={zoomScale === ZOOM_DEFAULT}
            className="flex items-center justify-center w-7 h-7 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            aria-label="Reset zoom (Ctrl 0)"
            title="Reset zoom (Ctrl 0)"
          >
            <RotateCcw size={13} />
          </button>
        </div>
      )}

      {/* Area documento — overflow-x-auto per scroll orizzontale quando zoomato */}
      <div
        ref={containerRef}
        className="flex-1 min-h-0 overflow-y-auto overflow-x-auto flex justify-center bg-muted/10 px-6 py-4"
      >
        <Document
          file={src}
          onLoadSuccess={onDocumentLoadSuccess}
          loading={
            <div className="flex flex-col items-center justify-center gap-3 py-12 text-muted-foreground">
              <span className="text-xs font-medium animate-pulse">Caricamento documento…</span>
            </div>
          }
          error={
            <div className="flex flex-col items-center justify-center gap-2 py-12 text-destructive">
              <span className="text-sm font-semibold">Impossibile caricare il PDF</span>
              <span className="text-xs text-muted-foreground">
                Verifica che il file sia un PDF valido o riprova più tardi.
              </span>
            </div>
          }
          noData={
            <div className="flex flex-col items-center justify-center gap-2 py-12 text-muted-foreground">
              <span className="text-xs">Nessun documento da visualizzare.</span>
            </div>
          }
        >
          {containerWidth > 0 && numPages > 0 && (
            <Page
              pageNumber={pageNumber}
              width={containerWidth}
              scale={zoomScale}
              renderTextLayer
              renderAnnotationLayer
              className="shadow-md rounded-sm overflow-hidden"
            />
          )}
        </Document>
      </div>


    </div>
  );
}
