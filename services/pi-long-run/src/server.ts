import http from "node:http";
import { URL } from "node:url";
import { createAionStreamMapper } from "./event-mapper.js";
import {
  abortPiSession,
  ensurePiSession,
  getPiSession,
  type SessionCreatePayload,
} from "./session-factory.js";

const PORT = Number(process.env.AION_PI_WORKER_PORT || "8791");
const HOST = process.env.AION_PI_WORKER_HOST || "127.0.0.1";
const SECRET = (process.env.AION_PI_WORKER_SECRET || "").trim();

function checkSecret(req: http.IncomingMessage): boolean {
  if (!SECRET) return true;
  return (req.headers["x-aion-pi-secret"] || "") === SECRET;
}

function readJson<T>(req: http.IncomingMessage): Promise<T> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        resolve(raw ? (JSON.parse(raw) as T) : ({} as T));
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

function writeJson(res: http.ServerResponse, status: number, body: unknown) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

const server = http.createServer(async (req, res) => {
  if (!checkSecret(req)) {
    writeJson(res, 403, { error: "forbidden" });
    return;
  }

  const url = new URL(req.url || "/", `http://127.0.0.1:${PORT}`);
  const path = url.pathname;

  if (req.method === "GET" && path === "/health") {
    writeJson(res, 200, { ok: true, service: "pi-long-run" });
    return;
  }

  if (req.method === "POST" && path === "/sessions") {
    try {
      const body = await readJson<SessionCreatePayload>(req);
      await ensurePiSession(body);
      writeJson(res, 200, { ok: true, session_id: body.session_id });
    } catch (err) {
      writeJson(res, 500, { error: String(err) });
    }
    return;
  }

  const sessionMatch = path.match(/^\/sessions\/([^/]+)(\/.*)?$/);
  if (!sessionMatch) {
    writeJson(res, 404, { error: "not found" });
    return;
  }

  const sessionId = decodeURIComponent(sessionMatch[1]);
  const sub = sessionMatch[2] || "";

  if (req.method === "POST" && sub === "/abort") {
    await abortPiSession(sessionId);
    writeJson(res, 200, { ok: true });
    return;
  }

  if (req.method === "GET" && sub === "/messages") {
    const session = getPiSession(sessionId);
    if (!session) {
      writeJson(res, 404, { error: "session not found" });
      return;
    }
    writeJson(res, 200, { messages: session.messages });
    return;
  }

  if (req.method === "POST" && sub === "/prompt") {
    const session = getPiSession(sessionId);
    if (!session) {
      writeJson(res, 404, { error: "session not found" });
      return;
    }

    const body = await readJson<{ message?: string }>(req);
    const message = (body.message || "").trim();
    if (!message) {
      writeJson(res, 400, { error: "message required" });
      return;
    }

    res.writeHead(200, {
      "Content-Type": "application/x-ndjson",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });

    const streamMapper = createAionStreamMapper();
    const unsubscribe = session.subscribe((event) => {
      for (const chunk of streamMapper.map(event)) {
        res.write(`${JSON.stringify(chunk)}\n`);
      }
    });

    try {
      await session.prompt(message);
      for (const chunk of streamMapper.flush()) {
        res.write(`${JSON.stringify(chunk)}\n`);
      }
      res.write(`${JSON.stringify({ type: "done" })}\n`);
    } catch (err) {
      res.write(
        `${JSON.stringify({ type: "error", content: String(err) })}\n`,
      );
      res.write(`${JSON.stringify({ type: "done" })}\n`);
    } finally {
      unsubscribe();
      res.end();
    }
    return;
  }

  writeJson(res, 404, { error: "not found" });
});

server.listen(PORT, HOST, () => {
  console.log(`[pi-long-run] listening on http://${HOST}:${PORT}`);
});
