/**
 * Base URL FastAPI AION (stesso host del backend).
 *
 * IMPORTANTE: usare SEMPRE questa funzione per costruire le URL del backend.
 * NON hardcodare `http://localhost:8001` nelle pagine: in Docker il browser
 * non puo' raggiungere quella porta (non e' esposta), e in produzione il
 * dominio cambia. Il bundle Next.js bakea `NEXT_PUBLIC_AION_API_URL` a
 * build-time (default `/api`, gestito da Caddy reverse-proxy).
 */
export const apiBase = (): string => {
  let url =
    (typeof process !== "undefined" && process.env.NEXT_PUBLIC_AION_API_URL) ||
    "http://localhost:8001";
  url = url.endsWith("/") ? url.slice(0, -1) : url;
  // Docker/Caddy uses `/api`; on `next dev` alone that hits the Next server, not FastAPI.
  if (
    typeof window !== "undefined" &&
    url === "/api" &&
    (window.location.port === "3870" || process.env.NODE_ENV === "development")
  ) {
    return "http://localhost:8001";
  }
  return url;
};
