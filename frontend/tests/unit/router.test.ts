import { afterEach, expect, it, vi } from "vitest";
import { authorizeRoute, routes } from "../../src/router";
import * as session from "../../src/composables/session";
import { ApiError } from "../../src/api/client";
afterEach(() => vi.restoreAllMocks());
it("declares every existing personal/admin URL and a fallback", () => {
  const children = routes.find((route) => route.path === "/")!.children!;
  expect(children.map((route) => route.path)).toEqual([
    "",
    "keys",
    "usage",
    "billing",
    "admin",
    "admin/settings",
    "admin/users",
  ]);
  expect(routes.some((route) => route.path === "/register")).toBe(true);
  expect(routes.some((route) => route.path === "/:pathMatch(.*)*")).toBe(true);
});
it("does not fetch a session for public sign-in pages", async () => {
  const read = vi.spyOn(session, "readSession");
  expect(await authorizeRoute({ path: "/login", meta: {} })).toBe(true);
  expect(read).not.toHaveBeenCalled();
});
it("redirects unauthenticated users before mounting protected content", async () => {
  vi.spyOn(session, "readSession").mockRejectedValue(
    new ApiError(401, "expired"),
  );
  expect(
    await authorizeRoute({ path: "/keys", meta: { protected: true } }),
  ).toBe("/login");
});
it("blocks regular users from admin routes and selects role-specific root", async () => {
  const read = vi
    .spyOn(session, "readSession")
    .mockResolvedValue({
      id: "fixture",
      email: "fixture@example.invalid",
      is_admin: false,
    });
  expect(
    await authorizeRoute({
      path: "/admin/users",
      meta: { protected: true, admin: true },
    }),
  ).toBe("/keys");
  expect(await authorizeRoute({ path: "/", meta: { protected: true } })).toBe(
    "/keys",
  );
  read.mockResolvedValue({
    id: "fixture",
    email: "fixture@example.invalid",
    is_admin: true,
  });
  expect(await authorizeRoute({ path: "/", meta: { protected: true } })).toBe(
    "/admin",
  );
});
it("reports an unavailable session store separately from an expired session", async () => {
  vi.spyOn(session, "readSession").mockRejectedValue(
    new ApiError(503, "storage unavailable"),
  );
  expect(
    await authorizeRoute({ path: "/keys", meta: { protected: true } }),
  ).toEqual({ path: "/login", query: { error: "会话校验失败，请稍后重试" } });
});
