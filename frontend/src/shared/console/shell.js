import { api, ensureCsrf } from "../http/client.js";
import { $, notice } from "../lib/dom.js";
import { requireSession } from "../auth/session.js";

export async function initChrome() {
  const account = $("account");
  const logout = $("logout");
  try {
    const user = await requireSession({ admin: document.body.dataset.page.startsWith("admin") });
    if (!user) return false;
    await ensureCsrf();
    if (account) account.textContent = user.email;
    if (user.is_admin && !document.body.dataset.page.startsWith("admin")) {
      const entry = document.createElement("a");
      entry.href = "/admin"; entry.className = "nav-link"; entry.textContent = "平台管理";
      document.querySelector(".console-nav").appendChild(entry);
    }
  } catch (error) {
    if (account) account.textContent = "未登录";
    notice("error", error.message);
    return false;
  }
  if (logout) {
    logout.addEventListener("click", async function () {
      logout.disabled = true;
      try {
        await api("/v1/auth/logout", { method: "POST", body: {} });
      } catch {
        /* 会话已失效时直接跳转 */
      }
      location.href = "/login";
    });
  }
  return true;
}
