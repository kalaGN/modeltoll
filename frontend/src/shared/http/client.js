export const CSRF_COOKIE = "laya_csrf";

export function readCookie(name) {
  const prefix = name + "=";
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith(prefix))
    ?.slice(prefix.length) ?? "";
}

let csrfPending;
export async function ensureCsrf() {
  if (readCookie(CSRF_COOKIE)) return;
  if (!csrfPending) {
    csrfPending = (async () => {
      const response = await fetch("/v1/auth/csrf", { credentials: "same-origin", cache: "no-store" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || typeof data.csrf_token !== "string" || !readCookie(CSRF_COOKIE)) throw new Error("安全令牌初始化失败，请刷新重试。");
    })().finally(() => { csrfPending = null; });
  }
  await csrfPending;
}

export async function api(path, { method = "GET", body = null } = {}) {
  if (method !== "GET") await ensureCsrf();
  const headers = {};
  if (body !== null) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = readCookie(CSRF_COOKIE);
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === null ? undefined : JSON.stringify(body),
  });
  if (response.status === 401) {
    location.href = "/login";
    throw new Error("登录状态已过期，正在跳转。");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw errorFrom(response.status, data);
  return data;
}

export function errorFrom(status, data) {
  if (typeof data.message === "string") return new Error(data.message);
  if (Array.isArray(data.detail)) {
    return new Error(`输入有误：${data.detail.map((i) => i.msg).filter(Boolean).join("；")}`);
  }
  if (typeof data.detail === "string") return new Error(data.detail);
  if (data.detail && typeof data.detail.message === "string") return new Error(data.detail.message);
  return new Error(`请求失败（${status}），请稍后重试。`);
}
