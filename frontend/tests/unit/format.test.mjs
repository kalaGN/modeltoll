import test from "node:test";
import assert from "node:assert/strict";
import { fmtInt, fmtTime, fmtAmount, fmtMs } from "../../src/shared/lib/format.js";
import { query } from "../../src/shared/lib/query.js";
import { errorFrom, api, ensureCsrf } from "../../src/shared/http/client.js";

test("formatting preserves UTC, decimal strings and missing values", () => {
  assert.equal(fmtInt(1000000), "1,000,000");
  assert.equal(fmtTime("2026-10-18T01:02:03"), "2026-10-18 01:02:03");
  assert.equal(fmtTime("2026-10-18T09:02:03+08:00"), "2026-10-18 01:02:03");
  assert.equal(fmtTime(null), "—");
  assert.equal(fmtTime("invalid"), "invalid");
  assert.equal(fmtAmount("9007199254740993.000001"), "9007199254740993.000001");
  assert.equal(fmtAmount(null), "0.000000");
  assert.equal(fmtMs(0), "0 ms");
  assert.equal(fmtMs(null), "—");
});

test("query keeps existing truthy-only parameter encoding", () => {
  assert.equal(query({ q: "a&b", limit: 20, empty: "", none: null, zero: 0 }), "?q=a%26b&limit=20");
  assert.equal(query({}), "");
});

test("HTTP error bodies retain existing flat/detail conventions", () => {
  assert.equal(errorFrom(403, { message: "Denied" }).message, "Denied");
  assert.equal(errorFrom(422, { detail: [{ msg: "invalid" }] }).message, "输入有误：invalid");
  assert.equal(errorFrom(500, { detail: "Unavailable" }).message, "Unavailable");
  assert.equal(errorFrom(500, {}).message, "请求失败（500），请稍后重试。");
});

test("shared request retains same-origin, CSRF, JSON and auth redirect", async t => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (...args) => {
    calls.push(args);
    return { status: 200, ok: true, json: async () => ({ done: true }) };
  });
  const priorDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
  const priorLocation = Object.getOwnPropertyDescriptor(globalThis, "location");
  globalThis.document = { cookie: "laya_csrf=synthetic; other=value" };
  globalThis.location = { href: "" };
  t.after(() => {
    if (priorDocument) Object.defineProperty(globalThis, "document", priorDocument); else delete globalThis.document;
    if (priorLocation) Object.defineProperty(globalThis, "location", priorLocation); else delete globalThis.location;
  });
  assert.deepEqual(await api("/v1/example", { method: "POST", body: { name: "sample" } }), { done: true });
  assert.equal(calls[0][1].credentials, "same-origin");
  assert.equal(calls[0][1].headers["X-CSRF-Token"], "synthetic");
  assert.equal(calls[0][1].body, '{"name":"sample"}');
  t.mock.method(globalThis, "fetch", async () => ({ status: 401 }));
  await assert.rejects(api("/v1/example"), /登录状态已过期/);
  assert.equal(location.href, "/login");
});

test("first visit initializes CSRF once and consumes its response", async t => {
  const prior = Object.getOwnPropertyDescriptor(globalThis, "document");
  globalThis.document = { cookie: "" };
  let calls = 0, consumed = 0;
  t.after(() => { if (prior) Object.defineProperty(globalThis, "document", prior); else delete globalThis.document; });
  t.mock.method(globalThis, "fetch", async () => {
    calls += 1;
    document.cookie = "laya_csrf=synthetic";
    return { ok: true, json: async () => { consumed += 1; return { csrf_token: "synthetic" }; } };
  });
  await Promise.all([ensureCsrf(), ensureCsrf()]);
  assert.equal(calls, 1);
  assert.equal(consumed, 1);
});
