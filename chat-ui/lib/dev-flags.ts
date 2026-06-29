/**
 * Feature toggles in source — chat-ui does not reliably read the repo root `.env`
 * with Next.js 16 + Turbopack (NEXT_PUBLIC_* compile to empty strings in client bundles).
 *
 * Backend snapshot capture still requires `AION_PROMPT_DEBUG=1` in the root `.env`.
 */
export const AION_PROMPT_DEBUG_UI_ENABLED = true;
export const AION_CHAT_STREAM_DEBUG_ENABLED = true;
