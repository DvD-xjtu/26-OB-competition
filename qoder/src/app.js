import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { AppError } from "./errors.js";
import { APP_NAME, APP_VERSION } from "./domain.js";
import { ResearchService } from "./research-service.js";

const PUBLIC_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "public",
);

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".txt": "text/plain; charset=utf-8",
  ".woff2": "font/woff2",
};

const SECURITY_HEADERS = {
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Resource-Policy": "same-origin",
  "Content-Security-Policy":
    "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'",
};

function sendJson(res, status, payload, { requestId, headers = {} } = {}) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    ...SECURITY_HEADERS,
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
    "X-Research-Relay-Request-ID": requestId,
    ...headers,
  });
  res.end(body);
}

function sendText(res, status, text, requestId) {
  res.writeHead(status, {
    ...SECURITY_HEADERS,
    "Content-Type": "text/plain; charset=utf-8",
    "Content-Length": Buffer.byteLength(text),
    "Cache-Control": "no-store",
    "X-Research-Relay-Request-ID": requestId,
  });
  res.end(text);
}

function sendMethodNotAllowed(res, allowed, requestId) {
  sendJson(
    res,
    405,
    {
      error: {
        code: "method_not_allowed",
        message: "不支持该 HTTP 方法。",
        details: { allowed },
        requestId,
      },
    },
    { requestId, headers: { Allow: allowed.join(", ") } },
  );
}

async function readJsonBody(req) {
  const contentType = String(req.headers["content-type"] || "").toLowerCase();
  if (!contentType.startsWith("application/json")) {
    throw new AppError(
      415,
      "unsupported_media_type",
      "请求体必须使用 application/json。",
    );
  }

  const chunks = [];
  let size = 0;
  let tooLarge = false;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 128 * 1024) {
      tooLarge = true;
    } else {
      chunks.push(chunk);
    }
  }

  if (tooLarge) {
    throw new AppError(413, "payload_too_large", "请求体超过 128KB 限制。");
  }
  if (chunks.length === 0) return {};

  let data;
  try {
    data = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new AppError(400, "invalid_json", "请求体不是有效的 JSON。");
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new AppError(400, "invalid_json", "请求体必须是 JSON 对象。");
  }
  return data;
}

async function serveStatic(req, res, pathname, requestId) {
  if (req.method !== "GET" && req.method !== "HEAD") {
    sendMethodNotAllowed(res, ["GET", "HEAD"], requestId);
    return;
  }

  let decoded;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    sendText(res, 400, "路径编码无效。", requestId);
    return;
  }

  const relativePath =
    decoded === "/" ? "index.html" : decoded.replace(/^\/+/, "");
  const segments = relativePath.split("/");
  if (
    !relativePath ||
    relativePath.includes("\0") ||
    relativePath.includes("\\") ||
    segments.some((segment) => segment.startsWith("."))
  ) {
    sendText(res, 404, "页面不存在。", requestId);
    return;
  }

  const filePath = path.resolve(PUBLIC_DIR, relativePath);
  const relativeToPublic = path.relative(PUBLIC_DIR, filePath);
  if (
    relativeToPublic.startsWith("..") ||
    path.isAbsolute(relativeToPublic)
  ) {
    sendText(res, 404, "页面不存在。", requestId);
    return;
  }

  let data;
  try {
    data = await fs.readFile(filePath);
  } catch (error) {
    if (error.code === "ENOENT" || error.code === "EISDIR") {
      sendText(res, 404, "页面不存在。", requestId);
      return;
    }
    throw error;
  }

  const extension = path.extname(filePath).toLowerCase();
  res.writeHead(200, {
    ...SECURITY_HEADERS,
    "Content-Type": MIME_TYPES[extension] || "application/octet-stream",
    "Content-Length": data.length,
    "Cache-Control": "no-cache",
    "X-Research-Relay-Request-ID": requestId,
  });
  if (req.method === "HEAD") {
    res.end();
  } else {
    res.end(data);
  }
}

function normalizePathname(raw) {
  const parsed = new URL(raw, "http://127.0.0.1");
  return parsed.pathname.length > 1
    ? parsed.pathname.replace(/\/+$/, "")
    : "/";
}

function decodeScopeSegment(segment) {
  try {
    return decodeURIComponent(segment);
  } catch {
    throw new AppError(400, "invalid_path", "研究任务路径编码无效。");
  }
}

export function createResearchRelayServer({ pc, config, logger = console }) {
  const service = new ResearchService({ pc, logger });

  const server = http.createServer((req, res) => {
    const requestId = `rr-${randomUUID()}`;
    const startedAt = process.hrtime.bigint();
    const method = String(req.method || "GET").toUpperCase();
    let pathname = "/";

    res.on("finish", () => {
      const elapsedMs =
        Number(process.hrtime.bigint() - startedAt) / 1_000_000;
      logger.info?.(
        `${method} ${pathname} ${res.statusCode} ${elapsedMs.toFixed(1)}ms ${requestId}`,
      );
    });

    const handle = async () => {
      pathname = normalizePathname(req.url || "/");

      if (pathname === "/api/health") {
        if (method !== "GET") {
          sendMethodNotAllowed(res, ["GET"], requestId);
          return;
        }
        const powercontext = await service.health();
        sendJson(
          res,
          200,
          {
            app: {
              name: APP_NAME,
              version: APP_VERSION,
              builtBy: "Qoder",
            },
            storage: {
              mode: "powercontext-http",
              localFallback: false,
              description:
                "研究数据仅通过 PowerContext HTTP API 读写；不使用本地 JSON 或模拟后端。",
            },
            powercontext,
            capabilities: {
              taskIsolation: "一个研究任务对应一个 PowerContext Scope",
              search: "PowerContext /v1/memory/search",
              handoff:
                "PowerContext Memory 列表 + Source 证据 + /v1/context/prepare",
            },
          },
          { requestId },
        );
        return;
      }

      if (pathname === "/api/tasks") {
        if (method === "GET") {
          const result = await service.listTasks();
          sendJson(
            res,
            200,
            {
              ...result,
              source: "powercontext",
              localFallback: false,
            },
            { requestId },
          );
          return;
        }
        if (method === "POST") {
          const body = await readJsonBody(req);
          const result = await service.createTask(body);
          sendJson(
            res,
            201,
            {
              ...result,
              source: "powercontext",
              localFallback: false,
            },
            { requestId },
          );
          return;
        }
        sendMethodNotAllowed(res, ["GET", "POST"], requestId);
        return;
      }

      const taskMatch =
        /^\/api\/tasks\/([^/]+)(?:\/(entries|search|handoff))?$/.exec(
          pathname,
        );

      if (taskMatch) {
        const scopeId = decodeScopeSegment(taskMatch[1]);
        const action = taskMatch[2] || null;

        if (!action) {
          if (method !== "GET") {
            sendMethodNotAllowed(res, ["GET"], requestId);
            return;
          }
          const result = await service.getTaskDetail(scopeId);
          sendJson(
            res,
            200,
            {
              ...result,
              source: "powercontext",
              localFallback: false,
            },
            { requestId },
          );
          return;
        }

        if (action === "entries") {
          if (method !== "POST") {
            sendMethodNotAllowed(res, ["POST"], requestId);
            return;
          }
          const body = await readJsonBody(req);
          const result = await service.addEntry(scopeId, body);
          sendJson(
            res,
            201,
            {
              ...result,
              saved: true,
              source: "powercontext",
              localFallback: false,
            },
            { requestId },
          );
          return;
        }

        if (action === "search") {
          if (method !== "POST") {
            sendMethodNotAllowed(res, ["POST"], requestId);
            return;
          }
          const body = await readJsonBody(req);
          const result = await service.searchEntries(scopeId, body);
          sendJson(
            res,
            200,
            {
              ...result,
              source: "powercontext",
              localFallback: false,
            },
            { requestId },
          );
          return;
        }

        if (action === "handoff") {
          if (method !== "GET") {
            sendMethodNotAllowed(res, ["GET"], requestId);
            return;
          }
          const result = await service.generateHandoff(scopeId);
          sendJson(
            res,
            200,
            {
              ...result,
              source: "powercontext",
              localFallback: false,
            },
            { requestId },
          );
          return;
        }
      }

      if (pathname.startsWith("/api/")) {
        sendJson(
          res,
          404,
          {
            error: {
              code: "not_found",
              message: "接口不存在。",
              details: null,
              requestId,
            },
          },
          { requestId },
        );
        return;
      }

      await serveStatic(req, res, pathname, requestId);
    };

    handle().catch((error) => {
      const status =
        Number.isInteger(error?.status) &&
        error.status >= 400 &&
        error.status <= 599
          ? error.status
          : 500;
      const code =
        typeof error?.code === "string" && error.code
          ? error.code
          : "internal_error";
      const message =
        status === 500 && !error?.status
          ? "服务器内部错误。"
          : error?.message || "请求失败。";

      if (status >= 500) {
        logger.warn?.(
          `[research-relay] ${requestId} ${method} ${pathname} -> ${status} ${code}: ${error?.message || "unknown"}`,
        );
      }

      if (res.headersSent) {
        res.destroy();
        return;
      }

      sendJson(
        res,
        status,
        {
          error: {
            code,
            message,
            details: error?.details ?? null,
            requestId,
          },
        },
        { requestId },
      );
    });
  });

  server.on("clientError", (error, socket) => {
    logger.warn?.(`[research-relay] client error: ${error.code || error.name}`);
    if (socket.writable) {
      socket.end("HTTP/1.1 400 Bad Request\r\n\r\n");
    }
  });

  return { server, service };
}
