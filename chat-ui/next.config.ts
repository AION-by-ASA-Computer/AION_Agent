import type { NextConfig } from "next";
import path from "path";
import fs from "fs";
import { loadEnvConfig } from "@next/env";

// Monorepo: le NEXT_PUBLIC_* vivono nel .env root (come il backend AION_*).
// chat-ui/.env.local resta override locale opzionale.
const repoRoot = path.resolve(__dirname, "..");
loadEnvConfig(repoRoot);

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
  // per immagini Docker compatte. Vedi docker/Dockerfile.chat-ui.
  output: "standalone",
  // Necessario perché lo standalone trace risale alla root del repo
  outputFileTracingRoot: path.resolve(__dirname, ".."),
  turbopack: {
    root: path.resolve(__dirname, ".."),
  },
  transpilePackages: ["tailwindcss", "@tailwindcss/postcss"],
  env: {
    NEXT_PUBLIC_AION_VERSION: version,
  },
};

export default nextConfig;
