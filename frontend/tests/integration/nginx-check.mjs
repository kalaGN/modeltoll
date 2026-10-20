// Optional verification against an existing nginx binary; never edits its global config.
import { mkdtemp, mkdir, readFile, writeFile, rm, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import http from "node:http";
import { fileURLToPath } from "node:url";
import { spawn, execFileSync } from "node:child_process";
import assert from "node:assert/strict";
import { createFixtureServer } from "../fixtures/server.mjs";

const root = fileURLToPath(new URL("../../", import.meta.url));
const temporary = await mkdtemp(path.join(tmpdir(), "laya-nginx-test-"));
const { server, state } = createFixtureServer();
const listen = server => new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
let child;
let childDone;
let exited;
try {
  const binary = process.env.NGINX_BIN || "nginx";
  let mime = process.env.NGINX_MIME;
  if (!mime) {
    for (const candidate of ["/etc/nginx/mime.types", "/opt/homebrew/etc/nginx/mime.types"]) {
      if (await access(candidate).then(() => true, () => false)) { mime = candidate; break; }
    }
  }
  if (!mime) throw new Error("Set NGINX_MIME to an existing mime.types file");
  await listen(server);
  const reservation = http.createServer();
  await listen(reservation);
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  const source = await readFile(path.join(root, "nginx.conf"), "utf8");
  const config = source.replaceAll("/tmp/", temporary + "/").replace("/etc/nginx/mime.types", mime).replaceAll("/usr/share/nginx/html", path.join(root, "dist")).replaceAll("http://app:8000", `http://127.0.0.1:${server.address().port}`).replace("listen 8080;", `listen 127.0.0.1:${port};`);
  const file = path.join(temporary, "nginx.conf");
  await mkdir(path.join(temporary, "logs"));
  await writeFile(file, config);
  execFileSync(binary, ["-t", "-p", temporary, "-c", file, "-e", "stderr"], { stdio: "pipe" });
  child = spawn(binary, ["-p", temporary, "-c", file, "-e", "stderr", "-g", "daemon off;"], { stdio: ["ignore", "ignore", "pipe"] });
  childDone = new Promise(resolve => { child.once("error", resolve); child.once("exit", code => { exited = code; resolve(); }); });
  child.stderr.resume();
  const base = `http://127.0.0.1:${port}`;
  let ready = false;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (exited !== undefined) throw new Error("Isolated nginx exited before ready");
    try { const response = await fetch(base + "/healthz"); await response.text(); ready = response.ok; } catch {}
    if (ready) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(ready, "Isolated nginx readiness");
  for (const route of ["/", "/login", "/register", "/keys", "/usage", "/billing", "/admin", "/admin/settings", "/admin/users"]) {
    const response = await fetch(base + route);
    assert.equal(response.status, 200, route);
    assert.match(response.headers.get("content-type"), /text\/html/, route);
    assert.match(response.headers.get("cache-control"), /no-store/);
    await response.text();
  }
  for (const route of ["/unknown", "/login.html", "/assets/login.html"]) {
    const response = await fetch(base + route); assert.equal(response.status, 404, route); await response.text();
  }
  const html = await readFile(path.join(root, "dist/index.html"), "utf8");
  const module = await fetch(base + html.match(/<script[^>]+src="([^"]+)"/)[1]);
  assert.equal(module.status, 200); assert.match(module.headers.get("content-type"), /javascript/); await module.text();
  const csrf = await fetch(base + "/v1/auth/csrf");
  assert.match(csrf.headers.get("set-cookie"), /laya_csrf=fixture/); await csrf.json();
  const redirect = await fetch(base + "/v1/redirect", { redirect: "manual" });
  assert.equal(redirect.headers.get("location"), base + "/v1/auth/me"); await redirect.text();
  const metadata = await fetch(base + "/v1/metadata");
  assert.equal(metadata.status, 429); assert.equal(metadata.headers.get("x-request-id"), "fixture-call");
  assert.equal(metadata.headers.get("retry-after"), "7"); await metadata.json();
  assert.equal(state.requests.filter(request => request.path === "/v1/metadata").length, 1);
  state.mode = "error";
  const failed = await fetch(base + "/v1/api-keys?limit=1");
  assert.equal(failed.status, 503); assert.equal((await failed.json()).message, "合成读取失败");
  assert.equal(state.requests.at(-1).query, "?limit=1");
  child.kill("SIGQUIT");
  await childDone;
  console.log("PASS: isolated nginx syntax, 9 page routes, MIME/cache, assets/404, Cookie and API proxy/error propagation; not a container build.");
} finally {
  if (child && exited === undefined) child.kill("SIGTERM");
  if (childDone) await childDone;
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
  await rm(temporary, { recursive: true, force: true });
}
