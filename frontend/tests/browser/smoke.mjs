// Optional real-browser checks. Supply an existing Playwright module; no production dependency.
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import assert from "node:assert/strict";
import { createFixtureServer } from "../fixtures/server.mjs";
import { createFrontendServer } from "../../scripts/serve.mjs";

const modulePath = process.env.LAYA_PLAYWRIGHT_MODULE;
const { chromium } = await import(modulePath ? pathToFileURL(path.resolve(modulePath)).href : "playwright");
const artifacts = fileURLToPath(new URL("../../../output/playwright/", import.meta.url));
const { server, state } = createFixtureServer();
await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
const frontend = createFrontendServer({ apiOrigin: `http://127.0.0.1:${server.address().port}` });
await new Promise((resolve, reject) => { frontend.once("error", reject); frontend.listen(0, "127.0.0.1", resolve); });
const base = `http://127.0.0.1:${frontend.address().port}`;
let browser;
try {
  browser = await chromium.launch({ headless: true, channel: process.env.LAYA_BROWSER_CHANNEL || "chrome" });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  if (process.env.LAYA_BROWSER_DEBUG) {
    page.on("request", request => console.log("request", new URL(request.url()).pathname));
    page.on("requestfinished", request => console.log("finished", new URL(request.url()).pathname));
  }
  const errors = [];
  let allow503 = false;
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => {
    if (!["error", "warning"].includes(message.type())) return;
    if (allow503 && message.text().includes("503")) return;
    errors.push(message.text());
  });
  page.on("requestfailed", request => errors.push(`${request.url()}: ${request.failure()?.errorText}`));
  await page.route("**/*", route => route.request().url().startsWith(base + "/") ? route.continue() : route.abort());
  const paths = ["/login", "/register", "/keys", "/usage", "/billing", "/admin", "/admin/settings", "/admin/users"];
  const visit = async route => {
    if (process.env.LAYA_BROWSER_DEBUG) console.log("Visiting", route);
    await page.goto(base + route);
    try { await page.waitForLoadState("networkidle"); }
    catch (error) { console.error("Last route", page.url(), "API paths", state.requests.slice(-12).map(request => request.path), "Errors", errors); throw error; }
    assert.deepEqual(errors, [], `Browser errors on ${route}`);
  };
  const action = async (selector, route, method = "GET", interact) => {
    await Promise.all([
      page.waitForResponse(response => new URL(response.url()).pathname === route && response.request().method() === method),
      interact ? interact() : page.locator(selector).click(),
    ]);
  };
  const waitText = async (selector, pattern) => {
    await page.waitForFunction(({ selector, pattern }) => new RegExp(pattern).test(document.querySelector(selector)?.textContent ?? ""), { selector, pattern });
  };
  await mkdir(artifacts, { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const route of paths) {
      state.requests = [];
      await visit(route);
      assert.equal(state.requests.filter(request => request.path === "/v1/platform/branding").length, route === "/admin/settings" ? 2 : 1);
      if (!["/login", "/register"].includes(route)) {
        assert.equal(state.requests.filter(request => request.path === "/v1/auth/me").length, 1);
        assert.equal(await page.locator("#account").textContent(), "fixture@example.invalid");
      }
      await page.screenshot({ path: path.join(artifacts, `${width}-${route.slice(1).replaceAll("/", "-")}.png`), fullPage: true, animations: "disabled" });
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await visit("/keys");
  await page.locator("#create").click();
  await page.keyboard.press("Escape");
  assert.equal(await page.locator("#create-modal").isVisible(), false);
  assert.equal(await page.locator("#create").evaluate(node => node === document.activeElement), true);
  await page.locator("#create").click();
  await page.locator("#key-name").fill("Synthetic browser key");
  await page.locator("#create-confirm").click();
  await page.locator("#secret-modal").waitFor({ state: "visible" });
  assert.equal(await page.locator("#secret").textContent(), "SYNTHETIC_KEY_NOT_VALID");
  await page.keyboard.press("Escape");
  assert.equal(await page.locator("#secret-modal").isVisible(), true);
  await page.locator("#close").click();
  assert.equal(await page.locator("#secret").textContent(), "");
  assert.ok(!(await page.locator("#example").textContent()).includes("SYNTHETIC_KEY_NOT_VALID"));
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await page.locator("#revoke-confirm").click();
  await page.getByRole("button", { name: "删除", exact: true }).waitFor();
  await page.getByRole("button", { name: "删除", exact: true }).click();
  await page.locator("#delete-confirm").click();
  await page.locator("#rows").getByText("还没有 API Key，点击右上角申请一个。", { exact: true }).waitFor();
  assert.ok((await page.locator("#rows").textContent()).includes("还没有 API Key"));

  await visit("/usage");
  await action("#next", "/v1/usage/calls");
  assert.ok(state.requests.some(request => request.path === "/v1/usage/calls" && request.query.includes("cursor=fixture-cursor")));
  await page.locator("#date-from").fill("2026-10-17");
  await action("#apply", "/v1/usage/summary");
  await waitText("#page-info", "第 1 页");
  assert.match(await page.locator("#page-info").textContent(), /第 1 页/);
  assert.ok(state.requests.some(request => request.path === "/v1/usage/summary" && request.query.includes("from=2026-10-17")));

  await visit("/billing");
  await action("#page-size", "/v1/billing/charges", "GET", () => page.locator("#page-size").selectOption("50"));
  assert.ok(state.requests.some(request => request.path === "/v1/billing/charges" && request.query.includes("limit=50")));
  assert.equal(await page.locator("#stat-amount").textContent(), "¥ 0.000010");

  await visit("/admin/settings");
  await page.locator("#platform-name").fill("Synthetic brand");
  assert.equal(await page.locator("#preview-name").textContent(), "Synthetic brand");
  await action("#save-settings", "/v1/admin/settings", "PUT");
  await waitText("#settings-status", "已保存");
  assert.match(await page.locator("#settings-status").textContent(), /已保存/);
  await action("#test-connection", "/v1/admin/model-connection/test", "POST");
  await waitText("#connection-status", "连接成功");
  assert.match(await page.locator("#connection-status").textContent(), /连接成功/);

  await visit("/admin/users");
  await action(null, "/v1/admin/users/fixture-member/api-keys", "GET", () => page.getByRole("button", { name: "查看 Key", exact: true }).click());
  await waitText("#keys-rows", "Synthetic key");
  assert.ok((await page.locator("#keys-rows").textContent()).includes("Synthetic key"));
  await page.getByRole("button", { name: "停用用户", exact: true }).click();
  await page.locator("#management-reason").fill("Synthetic browser verification");
  await action("#management-confirm", "/v1/admin/users/fixture-member/status", "PATCH");
  await waitText("#management-feedback", "操作已生效");
  assert.match(await page.locator("#management-feedback").textContent(), /操作已生效/);
  assert.ok(state.requests.filter(request => ["POST", "PUT", "PATCH", "DELETE"].includes(request.method)).every(request => request.csrf === "fixture"));

  for (const route of ["/keys", "/usage", "/billing", "/admin/users"]) {
    state.mode = "empty";
    await visit(route);
    assert.match(await page.locator("body").textContent(), /还没有|暂无|没有符合/);
  }
  state.mode = "success";
  allow503 = true;
  for (const [route, failed, notice] of [
    ["/usage", "/v1/usage/summary", "#error"],
    ["/billing", "/v1/billing/summary", "#error"],
    ["/admin", "/v1/admin/overview", "#error"],
    ["/admin/settings", "/v1/admin/model-connection", "#connection-error"],
    ["/admin/users", "/v1/admin/users", "#users-state"],
  ]) {
    state.failPaths = new Set([failed]);
    await visit(route);
    assert.match(await page.locator(notice).textContent(), /合成读取失败/);
  }
  state.failPaths.clear();
  allow503 = false;
  await visit("/login");
  await page.locator("#email").fill("fixture@example.invalid");
  await page.locator("#password").fill("synthetic-" + Date.now());
  await page.locator("#reveal").click();
  assert.equal(await page.locator("#password").getAttribute("type"), "text");
  await page.locator("#submit").click();
  await page.waitForURL(base + "/admin");
  await page.waitForLoadState("networkidle");
  assert.ok(state.requests.some(request => request.path === "/v1/auth/me" && request.sessionPresent));
  assert.deepEqual(errors, []);
  // Fresh browser cookie jars: static HTML never sets a CSRF cookie itself.
  for (const route of ["/login", "/register"]) {
    await page.context().clearCookies();
    state.requests = [];
    await visit(route);
    assert.equal(state.requests.filter(request => request.path === "/v1/auth/csrf").length, 1);
    assert.equal(await page.locator("#submit").isEnabled(), true);
  }
  const guardPage = await browser.newPage();
  guardPage.on("pageerror", error => errors.push(error.message));
  state.authenticated = false;
  state.requests = [];
  await guardPage.goto(base + "/keys");
  await guardPage.waitForURL(base + "/login");
  await guardPage.waitForLoadState("networkidle");
  assert.ok(!state.requests.some(request => request.path === "/v1/api-keys"));
  await guardPage.goto(base + "/");
  await guardPage.waitForURL(base + "/login");
  await guardPage.waitForLoadState("networkidle");
  state.authenticated = true;
  state.isAdmin = false;
  state.requests = [];
  await guardPage.goto(base + "/admin/users");
  await guardPage.waitForURL(base + "/keys");
  await guardPage.waitForLoadState("networkidle");
  assert.ok(!state.requests.some(request => request.path.startsWith("/v1/admin/")));
  state.isAdmin = true;
  await guardPage.goto(base + "/");
  await guardPage.waitForURL(base + "/admin");
  await guardPage.close();
  assert.deepEqual(errors, []);
  console.log("PASS: 8 routes x 2 viewports, Key lifecycle, filtering/paging, branding/model config, admin action, empty/error states, login and CSRF; synthetic services only.");
} finally {
  await browser?.close();
  await new Promise(resolve => frontend.close(resolve));
  await new Promise(resolve => server.close(resolve));
}
