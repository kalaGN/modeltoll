import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import tailwind from "@tailwindcss/vite";
import type { ProxyOptions } from "vite";

export function apiOrigin(value = "http://127.0.0.1:8000") {
  const url = new URL(value);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  )
    throw new Error("API_ORIGIN must be a fixed HTTP(S) origin");
  return url.origin;
}

function backendProxy(): ProxyOptions {
  return {
    target: apiOrigin(process.env.API_ORIGIN),
    changeOrigin: false,
    configure(proxy) {
      proxy.on("proxyReq", (outgoing, request) => {
        outgoing.removeHeader("forwarded");
        outgoing.removeHeader("x-real-ip");
        outgoing.setHeader(
          "x-forwarded-for",
          request.socket.remoteAddress || "127.0.0.1",
        );
        outgoing.setHeader("x-forwarded-proto", "http");
        outgoing.setHeader(
          "x-forwarded-host",
          request.headers.host || "localhost",
        );
      });
      proxy.on("proxyRes", (response) => {
        response.headers["cache-control"] = "no-store";
      });
    },
  };
}

export default defineConfig({
  plugins: [vue(), tailwind()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(
      ["/v1/", "/health", "/docs", "/redoc", "/openapi.json"].map((path) => [
        path,
        backendProxy(),
      ]),
    ),
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
    clearMocks: true,
  },
});
