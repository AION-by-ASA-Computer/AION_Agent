import type { NextConfig } from "next";
import path from "path";
import fs from "fs";

// Production Docker/Caddy: /admin. Local `next dev`: root (no prefix) unless overridden.
const basePath =
  process.env.NEXT_PUBLIC_BASE_PATH !== undefined
    ? process.env.NEXT_PUBLIC_BASE_PATH
    : process.env.NODE_ENV === "production"
      ? "/admin"
      : "";

// Leggi la versione dal file centralizzato version.json alla root del repository
let version = "v1.0.0";
try {
  const rootVersionPath = path.join(__dirname, "..", "version.json");
  if (fs.existsSync(rootVersionPath)) {
    const data = JSON.parse(fs.readFileSync(rootVersionPath, "utf-8"));
    if (data && data.version) {
      version = data.version;
    }
  }
} catch (e) {
  console.warn("Could not read version.json from workspace root:", e);
}

const nextConfig: NextConfig = {
  // 'standalone' produce un bundle self-contained con server.js minimale
  // per immagini Docker compatte. Vedi docker/Dockerfile.admin-ui.
  output: "standalone",
  outputFileTracingRoot: path.resolve(__dirname, ".."),
  basePath: basePath || undefined,
  // Configurazione Turbopack per Next.js 15/16
  // Utilizziamo la root del workspace per la risoluzione dei moduli
  turbopack: {
    root: path.resolve(__dirname, ".."),
  },
  // Assicuriamo la corretta gestione dei moduli Tailwind v4
  transpilePackages: ["tailwindcss", "@tailwindcss/postcss"],
  env: {
    NEXT_PUBLIC_AION_VERSION: version,
    NEXT_PUBLIC_BASE_PATH: basePath || "",
  },
};

export default nextConfig;
