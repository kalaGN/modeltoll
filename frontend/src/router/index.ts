import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
} from "vue-router";
import { ApiError } from "../api/client";
import { currentUser, readSession } from "../composables/session";
import LoginPage from "../pages/auth/LoginPage.vue";
import ConsoleLayout from "../layouts/ConsoleLayout.vue";

export const routes: RouteRecordRaw[] = [
  { path: "/login", component: LoginPage },
  { path: "/register", component: LoginPage },
  {
    path: "/",
    component: ConsoleLayout,
    meta: { protected: true },
    children: [
      { path: "", component: () => import("../pages/console/KeysPage.vue") },
      {
        path: "keys",
        component: () => import("../pages/console/KeysPage.vue"),
      },
      {
        path: "usage",
        component: () => import("../pages/console/ReportsPage.vue"),
      },
      {
        path: "billing",
        component: () => import("../pages/console/ReportsPage.vue"),
      },
      {
        path: "admin",
        component: () => import("../pages/admin/OverviewPage.vue"),
        meta: { admin: true },
      },
      {
        path: "admin/settings",
        component: () => import("../pages/admin/SettingsPage.vue"),
        meta: { admin: true },
      },
      {
        path: "admin/users",
        component: () => import("../pages/admin/UsersPage.vue"),
        meta: { admin: true },
      },
    ],
  },
  {
    path: "/:pathMatch(.*)*",
    component: () => import("../pages/NotFoundPage.vue"),
  },
];
export const router = createRouter({ history: createWebHistory(), routes });
export async function authorizeRoute(to: {
  meta: Record<string, unknown>;
  path: string;
}) {
  if (!to.meta.protected) return true;
  try {
    const user = await readSession();
    if (to.path === "/") return user.is_admin ? "/admin" : "/keys";
    if (to.meta.admin && !user.is_admin) return "/keys";
  } catch (error) {
    currentUser.value = null;
    if (error instanceof ApiError && error.status === 401) return "/login";
    // A storage outage is not proof of logout; show the retryable public error.
    return { path: "/login", query: { error: "会话校验失败，请稍后重试" } };
  }
}
router.beforeEach(authorizeRoute);
window.addEventListener("session-expired", () => {
  currentUser.value = null;
  void router.replace("/login");
});
