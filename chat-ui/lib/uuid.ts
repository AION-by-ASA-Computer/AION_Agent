/**
 * UUID v4 generator safe in insecure contexts.
 *
 * `crypto.randomUUID()` exists only in secure contexts (HTTPS / localhost): when the
 * chat-ui is served over plain HTTP on an IP or hostname (e.g. GHCR containers on a LAN)
 * it is undefined. `crypto.getRandomValues()` is available everywhere, so fall back to it.
 */
export function randomUUID(): string {
  const c = globalThis.crypto;
  if (typeof c?.randomUUID === "function") return c.randomUUID();

  const b = new Uint8Array(16);
  if (typeof c?.getRandomValues === "function") {
    c.getRandomValues(b);
  } else {
    for (let i = 0; i < b.length; i++) b[i] = Math.floor(Math.random() * 256);
  }
  b[6] = (b[6] & 0x0f) | 0x40; // version 4
  b[8] = (b[8] & 0x3f) | 0x80; // RFC 4122 variant

  const hex = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
