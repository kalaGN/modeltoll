// Isolated UI verification only: synthetic responses, no database or upstream model.
import http from "node:http";

const range = { from: "2026-10-17T00:00:00Z", to: "2026-10-19T00:00:00Z" };
const user = { id: "fixture-user", email: "fixture@example.invalid", is_admin: true, status: "active", created_at: range.from, last_login_at: range.from };
const item = { id: "fixture-key", name: "Synthetic key", display: "fixture…0000", status: "active", created_at: range.from, last_used_at: null };
const branding = { name: "Laya", description: "模型 API 平台", logo_url: "" };

export function createFixtureServer() {
  const state = { mode: "success", authenticated: true, isAdmin: true, failPaths: new Set(), requests: [], keys: [{ ...item }], memberKeys: [{ ...item }], members: [{ ...user, id: "fixture-member", is_admin: false }], audit: [] };
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://fixture.invalid");
    const route = url.pathname;
    const json = (value, status = 200, extraHeaders = {}) => {
      response.writeHead(status, { "Content-Type": "application/json", ...extraHeaders });
      response.end(JSON.stringify(value));
    };
    try {
      if (route.startsWith("/v1/")) {
        let body = "";
        for await (const chunk of request) body += chunk;
        state.requests.push({ method: request.method, path: route, query: url.search, body: body ? JSON.parse(body) : null, csrf: request.headers["x-csrf-token"], forwardedFor: request.headers["x-forwarded-for"], forwarded: request.headers.forwarded, sessionPresent: Boolean(request.headers.cookie?.includes("laya_session=synthetic")) });
        if (route === "/v1/auth/csrf") return json({ code: "ok", csrf_token: "fixture" }, 200, { "Set-Cookie": "laya_csrf=fixture; SameSite=Lax; Path=/" });
        if (route === "/v1/redirect") return json({}, 307, { Location: `http://${request.headers.host}/v1/auth/me` });
        if (route === "/v1/metadata") return json({ code: "synthetic_limit" }, 429, { "X-Request-Id": "fixture-call", "Retry-After": "7" });
        if (!["GET", "HEAD"].includes(request.method) && (request.headers["x-csrf-token"] !== "fixture" || !request.headers.cookie?.includes("laya_csrf=fixture"))) return json({ code: "csrf_failed", message: "合成 CSRF 校验失败" }, 403);
        if (route === "/v1/platform/branding") return json({ branding });
        if (route === "/v1/auth/me") return state.authenticated ? json({ user: { ...user, is_admin: state.isAdmin } }) : json({ code: "unauthenticated", message: "请登录" }, 401);
        if (state.mode === "error" || state.failPaths.has(route)) return json({ message: "合成读取失败" }, 503);
        if (route === "/v1/auth/login") { state.authenticated = true; return json({ user }, 200, { "Set-Cookie": "laya_session=synthetic; HttpOnly; SameSite=Lax; Path=/" }); }
        if (route === "/v1/auth/register") return json({}, 201);
        if (route === "/v1/auth/logout") { state.authenticated = false; return json({}); }
        const empty = state.mode === "empty";
        if (route === "/v1/api-keys" && request.method === "POST") {
          state.keys = [{ ...item, name: JSON.parse(body).name }];
          return json({ secret: "SYNTHETIC_KEY_NOT_VALID", call_example: "Bearer SYNTHETIC_KEY_NOT_VALID" }, 201);
        }
        if (route === "/v1/api-keys") return json({ items: empty ? [] : state.keys, summary: { total: empty ? 0 : state.keys.length, active: state.keys.filter(key => key.status === "active").length, revoked: 0 } });
        if (route.endsWith("/revoke")) {
          if (route.startsWith('/v1/admin/')) {
            state.memberKeys = state.memberKeys.map(key => ({ ...key, status: 'revoked' }));
            state.audit.push({ id: 'fixture-audit-' + state.audit.length, created_at: range.from, actor_email: user.email, target_email: state.members[0].email, action: 'api_key.revoked', previous_status: 'active', new_status: 'revoked', reason: JSON.parse(body).reason, target_key_id: item.id });
          } else state.keys = state.keys.map(key => ({ ...key, status: "revoked" }));
          return json({ changed: true });
        }
        if (request.method === "DELETE") { state.keys = []; return json({}); }
        if (route === "/v1/usage/summary") return json({ range, totals: { calls_total: empty ? 0 : 1, calls_succeeded: empty ? 0 : 1, calls_failed: 0, input_tokens: 10, calls_in_progress: 0, billing_pending_count: 0 }, series: empty ? [] : [{ date: "2026-10-18", succeeded: 1, failed: 0 }] });
        if (route === "/v1/usage/calls") return json({ items: empty ? [] : [{ request_id: "fixture-call", api_key: item.display, endpoint: "/v1/predict", started_at: range.from, status: "succeeded", input_tokens: 10, duration_ms: 20 }], has_more: !url.searchParams.has("cursor") && !empty, next_cursor: "fixture-cursor" });
        if (route === "/v1/billing/summary") return json({ range, price: { version: "fixture", unit_price_yuan: "1.000000", unit_tokens: 1000000, currency: "CNY", billing_policy_version: "succeeded_only_v1" }, totals: { charge_count: empty ? 0 : 1, billable_tokens: 10, charged_amount_yuan: "0.000010", calls_total: 1, billing_pending_count: 0 }, series: empty ? [] : [{ date: "2026-10-18", amount_yuan: "0.000010" }] });
        if (route === "/v1/billing/charges") return json({ items: empty ? [] : [{ request_id: "fixture-call", api_key: item.display, billable_tokens: 10, unit_tokens: 1000000, unit_price_yuan: "1", pricing_version: "fixture", amount_yuan: "0.000010" }], has_more: false });
        if (route === "/v1/admin/overview") return json({ range, totals: { users: 1, active_keys: 1, calls: empty ? 0 : 1, amount_yuan: "0.000010" }, series: empty ? [] : [{ date: "2026-10-18", calls: 1, amount_yuan: "0.000010" }] });
        if (route === "/v1/admin/settings") return json({ branding: { ...branding, ...JSON.parse(body) } });
        if (route === "/v1/admin/model-connection/test") return json({ model: "fixture-model" });
        if (route === "/v1/admin/model-connection") return json({ runtime: "external", credential_configured: false, connection: { base_url: "http://127.0.0.1:11434/v1", model: "fixture-model", timeout_seconds: 30, enabled: true } });
        if (route === "/v1/admin/users") return json({ items: empty ? [] : state.members, page: 1, total: empty ? 0 : state.members.length, has_more: false });
        if (route.endsWith("/status")) {
          state.members[0].status = JSON.parse(body).status;
          state.audit.push({ id: 'fixture-audit-' + state.audit.length, created_at: range.from, actor_email: user.email, target_email: state.members[0].email, action: 'user.status_changed', previous_status: state.members[0].status === 'active' ? 'disabled' : 'active', new_status: state.members[0].status, reason: JSON.parse(body).reason, target_key_id: null });
          return json({ changed: true, user: state.members[0] });
        }
        if (route.endsWith("/api-keys")) return json({ items: empty ? [] : state.memberKeys, user, page: 1, total: 1, has_more: false });
        if (route === "/v1/admin/audit-events") return json({ items: empty ? [] : state.audit, page: 1, total: state.audit.length, has_more: false });
        return json({ message: "Fixture route missing" }, 404);
      }
      response.writeHead(404); response.end("API fixture only");
    } catch { response.writeHead(500); response.end("Fixture failed"); }
  });
  return { server, state };
}
