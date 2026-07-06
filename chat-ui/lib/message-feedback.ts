/** Client-side thumbs up/down per message (no server API yet). */

export type MessageRating = 1 | -1;

const STORAGE_KEY = "aion_message_ratings";

function readAll(): Record<string, MessageRating> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, number>;
    const out: Record<string, MessageRating> = {};
    for (const [id, v] of Object.entries(parsed)) {
      if (v === 1 || v === -1) out[id] = v;
    }
    return out;
  } catch {
    return {};
  }
}

function writeAll(map: Record<string, MessageRating>): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    /* quota */
  }
}

export function toggleMessageRating(messageId: string, rating: MessageRating): MessageRating | null {
  const map = readAll();
  if (map[messageId] === rating) {
    delete map[messageId];
    writeAll(map);
    return null;
  }
  map[messageId] = rating;
  writeAll(map);
  return rating;
}

export function loadMessageRatings(): Record<string, MessageRating> {
  return readAll();
}

export function clearMessageRating(messageId: string): void {
  const map = readAll();
  delete map[messageId];
  writeAll(map);
}
