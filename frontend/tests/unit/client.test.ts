import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, ensureCsrf, errorMessage } from "../../src/api/client";
import { query } from "../../src/api/query";
import { apiOrigin } from "../../vite.config";

beforeEach(() => {
  document.cookie = "laya_csrf=; Max-Age=0; Path=/";
});
afterEach(() => vi.restoreAllMocks());
function response(value: unknown, status = 200) {
  return { status, ok: status < 400, json: async () => value } as Response;
}
describe("HTTP compatibility", () => {
  it("preserves query encoding and omitted empty/zero values", () => {
    expect(query({ q: "a&b", limit: 20, empty: "", none: null, zero: 0 })).toBe(
      "?q=a%26b&limit=20",
    );
    expect(query({})).toBe("");
  });
  it("accepts flat/detail errors without rendering untrusted HTML", () => {
    expect(errorMessage(403, { message: "Denied" })).toBe("Denied");
    expect(errorMessage(422, { detail: [{ msg: "invalid" }] })).toBe(
      "输入有误：invalid",
    );
    expect(errorMessage(500, { detail: "Unavailable" })).toBe("Unavailable");
    expect(errorMessage(500, { detail: { message: "Nested" } })).toBe("Nested");
    expect(errorMessage(500, {})).toBe("请求失败（500），请稍后重试。");
  });
  it("uses same-origin cookies, CSRF, JSON and propagates AbortSignal", async () => {
    document.cookie = "laya_csrf=synthetic; Path=/";
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(response({ done: true }));
    const signal = new AbortController().signal;
    await expect(
      api("/v1/example", { method: "POST", body: { name: "sample" }, signal }),
    ).resolves.toEqual({ done: true });
    expect(fetch).toHaveBeenCalledWith(
      "/v1/example",
      expect.objectContaining({
        credentials: "same-origin",
        signal,
        body: '{"name":"sample"}',
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": "synthetic",
        },
      }),
    );
  });
  it("initializes CSRF only once on concurrent first writes", async () => {
    let consumed = 0;
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      document.cookie = "laya_csrf=synthetic; Path=/";
      return {
        ok: true,
        json: async () => {
          consumed++;
          return { csrf_token: "synthetic" };
        },
      } as Response;
    });
    await Promise.all([ensureCsrf(), ensureCsrf()]);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(consumed).toBe(1);
  });
  it("fails closed if CSRF cookie was not issued", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response({ csrf_token: "not-set" }),
    );
    await expect(ensureCsrf()).rejects.toThrow("安全令牌初始化失败");
  });
  it("signals expired protected requests but leaves login failures on the form", async () => {
    const listener = vi.fn();
    window.addEventListener("session-expired", listener);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response({ message: "未登录" }, 401),
    );
    await expect(api("/v1/example")).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalledOnce();
    document.cookie = "laya_csrf=synthetic; Path=/";
    await expect(
      api("/v1/auth/login", { method: "POST", body: {} }),
    ).rejects.toThrow("未登录");
    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener("session-expired", listener);
  });
  it("restricts the development API proxy to one fixed origin", () => {
    for (const value of [
      "file:///tmp",
      "http://user:pass@localhost",
      "http://localhost/path",
      "http://localhost/?q=1",
    ])
      expect(() => apiOrigin(value)).toThrow();
    expect(apiOrigin("http://127.0.0.1:8000")).toBe("http://127.0.0.1:8000");
  });
});
