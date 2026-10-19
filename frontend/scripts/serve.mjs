// Loopback development server only. Production uses nginx.conf.
import http from "node:http";
import https from "node:https";
import { readFile, realpath } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const pages = Object.freeze({ "/": "index.html", "/login": "login.html", "/register": "login.html", "/keys": "api-keys.html", "/usage": "usage.html", "/billing": "billing.html", "/admin": "admin.html", "/admin/settings": "admin-settings.html", "/admin/users": "admin-users.html" });
const defaultDist = fileURLToPath(new URL("../dist/", import.meta.url));
const hop = new Set(["connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"]);
function headersWithoutHop(headers) {
  const excluded = new Set([...hop, ...(headers.connection || "").split(",").map(value => value.trim().toLowerCase())]);
  return Object.fromEntries(Object.entries(headers).filter(([name]) => !excluded.has(name.toLowerCase())));
}

export function staticPath(rawPath) {
  if (pages[rawPath]) return pages[rawPath];
  if (!rawPath.startsWith("/assets/")) return null;
  let relative;
  try { relative = decodeURIComponent(rawPath.slice(8)); } catch { return null; }
  if (!relative || relative.includes("\\") || relative.split("/").some(part => !part || part === "." || part === "..") || relative.includes("\0") || relative.endsWith(".html")) return null;
  return relative;
}

export function createFrontendServer({ apiOrigin = "http://127.0.0.1:8000", dist = defaultDist } = {}) {
  const upstream = new URL(apiOrigin);
  if (!["http:", "https:"].includes(upstream.protocol) || upstream.username || upstream.password || upstream.pathname !== "/" || upstream.search || upstream.hash) throw new Error("API origin must be a fixed HTTP(S) origin without credentials or a path");
  const transport = upstream.protocol === "https:" ? https : http;
  const root = path.resolve(dist);
  return http.createServer(async (request, response) => {
    // Do not normalize dot segments before checking static paths, or act as an open proxy.
    const raw = request.url || "/";
    if (!raw.startsWith("/") || raw.startsWith("//")) { response.writeHead(400); return response.end(); }
    const pathname = raw.split("?")[0];
    if (pathname.startsWith("/v1/") || ["/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"].includes(pathname)) {
      const headers = headersWithoutHop(request.headers);
      delete headers.forwarded; delete headers["x-real-ip"];
      headers["x-forwarded-for"] = request.socket.remoteAddress;
      headers["x-forwarded-proto"] = "http";
      headers["x-forwarded-host"] = request.headers.host;
      // Preserve the browser-facing authority for backend-generated redirects.
      headers.host = request.headers.host || upstream.host;
      const proxy = transport.request(upstream, { method: request.method, path: raw, headers }, incoming => {
        const outgoing = headersWithoutHop(incoming.headers);
        outgoing["cache-control"] = "no-store";
        response.writeHead(incoming.statusCode, outgoing);
        incoming.on("error", () => response.destroy());
        incoming.pipe(response);
      });
      proxy.on("error", () => {
        if (response.headersSent) return response.destroy();
        response.writeHead(502, { "Content-Type": "application/json", "Cache-Control": "no-store" });
        response.end(JSON.stringify({ code: "api_unavailable", message: "后端服务不可用" }));
      });
      request.on("aborted", () => proxy.destroy());
      request.on("error", () => proxy.destroy());
      response.on("error", () => proxy.destroy());
      response.on("close", () => { if (!response.writableEnded) proxy.destroy(); });
      request.pipe(proxy);
      return;
    }
    if (!["GET", "HEAD"].includes(request.method)) { response.writeHead(405, { Allow: "GET, HEAD" }); return response.end(); }
    const relative = staticPath(pathname);
    if (!relative) { response.writeHead(404); return response.end("Not found"); }
    try {
      const file = await realpath(path.join(root, relative));
      if (!file.startsWith(root + path.sep)) { response.writeHead(404); return response.end(); }
      const content = await readFile(file);
      const mime = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp" }[path.extname(file)] || "application/octet-stream";
      response.writeHead(200, { "Content-Type": mime, "Cache-Control": file.endsWith(".html") ? "no-store" : "no-cache", "X-Content-Type-Options": "nosniff" });
      response.end(request.method === "HEAD" ? undefined : content);
    } catch { response.writeHead(404); response.end("Not found; build frontend first"); }
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.FRONTEND_PORT || 5173);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid frontend port");
  const server = createFrontendServer({ apiOrigin: process.env.API_ORIGIN });
  server.on("error", error => { console.error(error.message); process.exitCode = 1; });
  server.listen(port, "127.0.0.1", () => console.log(`Frontend: http://127.0.0.1:${port} (API proxy enabled)`));
}
