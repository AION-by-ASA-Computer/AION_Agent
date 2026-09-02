"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { AttachmentRef } from "@/lib/attachments";
import { uploadSessionFileWithProgress } from "@/lib/api/aion";

export type PendingUploadStatus = "queued" | "uploading" | "done" | "error";

export type PendingUploadItem = {
  id: string;
  file: File;
  status: PendingUploadStatus;
  progress: number;
  attachment?: AttachmentRef;
  error?: string;
};

function fileKey(file: File): string {
  return `${file.name}\0${file.size}`;
}

export function usePendingSessionUploads(
  conversationId: string,
  userId: string,
  token?: string | null,
) {
  const [items, setItems] = useState<PendingUploadItem[]>([]);
  const abortByIdRef = useRef<Map<string, AbortController>>(new Map());
  const itemsRef = useRef(items);
  itemsRef.current = items;

  const abortOne = useCallback((id: string) => {
    abortByIdRef.current.get(id)?.abort();
    abortByIdRef.current.delete(id);
  }, []);

  const abortAll = useCallback(() => {
    for (const ctrl of abortByIdRef.current.values()) {
      ctrl.abort();
    }
    abortByIdRef.current.clear();
  }, []);

  useEffect(() => {
    abortAll();
    setItems([]);
  }, [conversationId, abortAll]);

  const startUpload = useCallback(
    (id: string, file: File) => {
      abortOne(id);
      const ctrl = new AbortController();
      abortByIdRef.current.set(id, ctrl);

      setItems((prev) =>
        prev.map((it) =>
          it.id === id
            ? { ...it, status: "uploading", progress: 0, error: undefined, attachment: undefined }
            : it,
        ),
      );

      void uploadSessionFileWithProgress(conversationId, userId, file, token, {
        signal: ctrl.signal,
        onProgress: (pct) => {
          setItems((prev) =>
            prev.map((it) => (it.id === id ? { ...it, progress: pct } : it)),
          );
        },
      })
        .then(({ attachment }) => {
          abortByIdRef.current.delete(id);
          setItems((prev) =>
            prev.map((it) =>
              it.id === id
                ? { ...it, status: "done", progress: 100, attachment, error: undefined }
                : it,
            ),
          );
        })
        .catch((err: unknown) => {
          abortByIdRef.current.delete(id);
          if (err instanceof DOMException && err.name === "AbortError") {
            return;
          }
          const message = err instanceof Error ? err.message : "upload failed";
          setItems((prev) =>
            prev.map((it) =>
              it.id === id ? { ...it, status: "error", error: message } : it,
            ),
          );
        });
    },
    [abortOne, conversationId, token, userId],
  );

  const queueFiles = useCallback(
    (files: File[]) => {
      if (!files.length) return;
      const existing = new Set(itemsRef.current.map((it) => fileKey(it.file)));
      const toAdd: PendingUploadItem[] = [];
      for (const file of files) {
        const key = fileKey(file);
        if (existing.has(key)) continue;
        existing.add(key);
        toAdd.push({
          id: crypto.randomUUID(),
          file,
          status: "queued",
          progress: 0,
        });
      }
      if (!toAdd.length) return;

      setItems((prev) => [...prev, ...toAdd]);
      for (const item of toAdd) {
        startUpload(item.id, item.file);
      }
    },
    [startUpload],
  );

  const removeItem = useCallback(
    (id: string) => {
      abortOne(id);
      setItems((prev) => prev.filter((it) => it.id !== id));
    },
    [abortOne],
  );

  const retryItem = useCallback(
    (id: string) => {
      const row = itemsRef.current.find((it) => it.id === id);
      if (!row) return;
      startUpload(id, row.file);
    },
    [startUpload],
  );

  const clearAll = useCallback(() => {
    abortAll();
    setItems([]);
  }, [abortAll]);

  const isUploading = items.some(
    (it) => it.status === "queued" || it.status === "uploading",
  );
  const hasUploadErrors = items.some((it) => it.status === "error");
  const completedAttachments = items
    .filter((it) => it.status === "done" && it.attachment)
    .map((it) => it.attachment!);

  return {
    items,
    queueFiles,
    removeItem,
    retryItem,
    clearAll,
    isUploading,
    hasUploadErrors,
    completedAttachments,
  };
}
