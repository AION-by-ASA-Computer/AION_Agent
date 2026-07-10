"use client";

import React, { useState, useRef, useEffect } from "react";
import { UploadCloud } from "lucide-react";
import { useT } from "@/lib/i18n/use-t";

interface ChatDragDropProps {
  onFilesDropped: (files: File[]) => void;
  children: React.ReactNode;
}

export function ChatDragDrop({ onFilesDropped, children }: ChatDragDropProps) {
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);
  const t = useT();

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer?.types && e.dataTransfer.types.includes("Files")) {
      dragCounter.current++;
      if (dragCounter.current === 1) {
        setIsDragging(true);
      }
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current--;
    if (dragCounter.current <= 0) {
      dragCounter.current = 0;
      setIsDragging(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = "copy";
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setIsDragging(false);

    if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
      const files = Array.from(e.dataTransfer.files);
      onFilesDropped(files);
      e.dataTransfer.clearData();
    }
  };

  // Reset drag counter if window loses focus or drag is cancelled globally
  useEffect(() => {
    const handleDragEnd = () => {
      dragCounter.current = 0;
      setIsDragging(false);
    };
    window.addEventListener("dragend", handleDragEnd);
    return () => {
      window.removeEventListener("dragend", handleDragEnd);
    };
  }, []);

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className="relative flex min-h-0 min-w-0 flex-1 flex-col"
    >
      {children}
      {isDragging && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-background/80 backdrop-blur-md transition-all duration-300 animate-in fade-in-0">
          <div className="m-4 flex flex-col items-center justify-center gap-4 rounded-3xl border-2 border-dashed border-primary/40 bg-primary/5 p-8 text-center max-w-md w-[calc(100%-2rem)] shadow-lg animate-in zoom-in-95 duration-200">
            <div className="flex size-16 items-center justify-center rounded-full bg-primary/10 text-primary animate-bounce">
              <UploadCloud size={32} />
            </div>
            <div>
              <h3 className="text-xl font-bold text-foreground">
                {t("chat.tools.drag_drop_title")}
              </h3>
              <p className="text-sm text-muted-foreground mt-2 max-w-xs leading-relaxed">
                {t("chat.tools.drag_drop_desc")}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
