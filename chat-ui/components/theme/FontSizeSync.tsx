"use client";

import { useEffect } from "react";
import { applyChatFontSize, readChatFontSize } from "@/lib/theme/chat-font-scale";

/** Re-applies stored font size after hydration (keeps slider + layout script in sync). */
export function FontSizeSync() {
  useEffect(() => {
    applyChatFontSize(readChatFontSize());
  }, []);
  return null;
}
