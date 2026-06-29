import { createHmac } from "crypto";
import { NextRequest, NextResponse } from "next/server";
import { adminUiBase } from "@/lib/config";

function embedSecret(): string {
  return (
    process.env.AION_AGENT_DB_EMBED_SECRET ||
    process.env.AION_AGENT_DB_INTERNAL_SECRET ||
    "aion-db-embed"
  );
}

function makeEmbedToken(userId: string, ttlSec = 3600): string {
  const exp = Math.floor(Date.now() / 1000) + ttlSec;
  const payload = `${userId}:${exp}`;
  const sig = createHmac("sha256", embedSecret()).update(payload).digest("hex");
  const raw = `${payload}:${sig}`;
  return Buffer.from(raw, "utf8").toString("base64url");
}

/** Restituisce URL iframe Agent DB (admin-ui), come Chainlit `_open_db_sidebar_editor`. */
export async function GET(req: NextRequest) {
  const userId = req.nextUrl.searchParams.get("userId")?.trim();
  if (!userId) {
    return NextResponse.json({ error: "missing userId" }, { status: 400 });
  }
  const tableHint = req.nextUrl.searchParams.get("table")?.trim();
  const token = makeEmbedToken(userId);
  const base = adminUiBase();
  const q = new URLSearchParams({ embedded: "1", token });
  if (tableHint) q.set("table", tableHint);
  const url = `${base}/agent-db/${encodeURIComponent(userId)}?${q.toString()}`;
  return NextResponse.json({ url });
}
