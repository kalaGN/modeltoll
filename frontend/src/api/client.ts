export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export function readCookie(name: string) {
  return (
    document.cookie
      .split("; ")
      .find((row) => row.startsWith(name + "="))
      ?.slice(name.length + 1) ?? ""
  );
}
let pending: Promise<void> | undefined;
export async function ensureCsrf() {
  if (readCookie("laya_csrf")) return;
  if (!pending)
    pending = (async () => {
      const response = await fetch("/v1/auth/csrf", {
        credentials: "same-origin",
        cache: "no-store",
      });
      const body = await response.json().catch(() => ({}));
      if (
        !response.ok ||
        typeof body.csrf_token !== "string" ||
        !readCookie("laya_csrf")
      )
        throw new Error("安全令牌初始化失败，请刷新重试。");
    })().finally(() => {
      pending = undefined;
    });
  await pending;
}
export function errorMessage(
  status: number,
  data: Record<string, unknown>,
): string {
  if (typeof data.message === "string") return data.message;
  if (Array.isArray(data.detail))
    return (
      "输入有误：" +
      data.detail
        .map((item) => item.msg)
        .filter(Boolean)
        .join("；")
    );
  if (typeof data.detail === "string") return data.detail;
  if (
    data.detail &&
    typeof data.detail === "object" &&
    "message" in data.detail &&
    typeof data.detail.message === "string"
  )
    return data.detail.message;
  return `请求失败（${status}），请稍后重试。`;
}
export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const { method = "GET", body, signal } = options;
  if (method !== "GET") await ensureCsrf();
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = readCookie("laya_csrf");
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    cache: "no-store",
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (
      response.status === 401 &&
      !["/v1/auth/login", "/v1/auth/me", "/v1/auth/register"].includes(path)
    )
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(response.status, errorMessage(response.status, data));
  }
  return data as T;
}
