import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createFixtureServer } from "../fixtures/server.mjs";
import { createFrontendServer } from "../../scripts/serve.mjs";

const listen = server => new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
const close = server => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); });

test("real static/proxy servers preserve paths, cookies, CSRF/errors and fail closed", async () => {
  const { server: api, state } = createFixtureServer();
  await listen(api);
  const frontend = createFrontendServer({ apiOrigin: `http://127.0.0.1:${api.address().port}` });
  await listen(frontend);
  const base = `http://127.0.0.1:${frontend.address().port}`;
  let apiClosed = false;
  try {
    assert.equal((await fetch(base + "/admin/users")).status, 200);
    assert.equal((await fetch(base + "/unknown")).status, 404);
    assert.equal((await fetch(base + "/assets/%252e%252e/.env")).status, 404);
    const html = await readFile(new URL('../../dist/index.html', import.meta.url), 'utf8');
    const entry = html.match(/<script[^>]+src="([^"]+)"/)[1];
    assert.equal((await fetch(base + entry)).headers.get("content-type"), "text/javascript; charset=utf-8");
    const csrf = await fetch(base + "/v1/auth/csrf");
    assert.match(csrf.headers.get("set-cookie"), /laya_csrf=fixture/);
    await csrf.json();
    const identity = await fetch(base + "/v1/auth/me", { headers: { "X-Forwarded-For": "spoofed", Forwarded: "for=spoofed" } });
    await identity.json();
    assert.equal(state.requests.at(-1).forwardedFor, "127.0.0.1");
    assert.equal(state.requests.at(-1).forwarded, undefined);
    const redirect = await fetch(base + "/v1/redirect", { redirect: "manual" });
    assert.equal(redirect.headers.get("location"), base + "/v1/auth/me");
    await redirect.text();
    const metadata = await fetch(base + "/v1/metadata");
    assert.equal(metadata.status, 429);
    assert.equal(metadata.headers.get("x-request-id"), "fixture-call");
    assert.equal(metadata.headers.get("retry-after"), "7");
    assert.equal((await metadata.json()).code, "synthetic_limit");
    assert.equal(state.requests.filter(request => request.path === "/v1/metadata").length, 1);
    const denied = await fetch(base + "/v1/api-keys", { method: "POST", headers: { "Content-Type": "application/json" }, body: '{"name":"synthetic"}' });
    assert.equal(denied.status, 403);
    assert.equal((await denied.json()).code, "csrf_failed");
    const created = await fetch(base + "/v1/api-keys?source=proxy", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": "fixture", Cookie: "laya_csrf=fixture" }, body: '{"name":"proxy"}' });
    assert.equal(created.status, 201);
    await created.json();
    assert.equal(state.requests.at(-1).query, "?source=proxy");
    assert.equal(state.requests.at(-1).body.name, "proxy");
    state.mode = "error";
    const failed = await fetch(base + "/v1/api-keys");
    assert.equal(failed.status, 503);
    assert.equal((await failed.json()).message, "合成读取失败");
    await close(api); apiClosed = true;
    const unavailable = await fetch(base + "/v1/auth/me");
    assert.equal(unavailable.status, 502);
    assert.equal((await unavailable.json()).code, "api_unavailable");
  } finally { await close(frontend); if (!apiClosed) await close(api); }
});
