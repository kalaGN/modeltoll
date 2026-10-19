import { readCookie, ensureCsrf } from "../shared/http/client.js";
import { initBranding } from "../shared/console/branding.js";

const form = document.getElementById("form");
  const alertBox = document.getElementById("alert");
  const submit = document.getElementById("submit");
  const email = document.getElementById("email");
  const password = document.getElementById("password");
  const params = new URLSearchParams(location.search);
  const mode = params.get("mode") === "register" || location.pathname === "/register";


  if (mode) {
    document.getElementById("title").textContent = "创建账号";
    document.getElementById("subtitle").textContent = "注册后即可登录 Laya 模型 API 平台。";
    document.getElementById("modeHint").textContent = "密码长度需为 8–128 个字符。";
    submit.textContent = "注册";
    password.setAttribute("autocomplete", "new-password");
    document.getElementById("switch").innerHTML =
      '已有账号？<a href="/login" class="font-semibold text-brand-500 hover:underline">直接登录</a>';
  }

  document.getElementById("reveal").addEventListener("click", function () {
    const shown = password.type === "text";
    password.type = shown ? "password" : "text";
    this.setAttribute("aria-pressed", String(!shown));
    this.setAttribute("aria-label", shown ? "显示密码" : "隐藏密码");
  });

  function show(kind, message) {
    alertBox.textContent = message;
    alertBox.className =
      "mb-5 rounded-[10px] border px-3.5 py-3 text-[13.5px] leading-relaxed " +
      (kind === "error"
        ? "border-red-200 bg-red-50 text-red-700"
        : "border-green-200 bg-green-50 text-green-700");
  }

  function hideAlert() {
    alertBox.className = "mb-5 hidden rounded-[10px] border px-3.5 py-3 text-[13.5px]";
  }

  if (params.has("registered")) show("success", "注册成功，请使用新账号登录。");

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    hideAlert();
    [email, password].forEach((el) => el.setAttribute("aria-invalid", "false"));
    if (!email.value.trim() || !password.value) {
      show("error", "请填写邮箱和密码。");
      return;
    }
    const csrfToken = readCookie("laya_csrf");
    if (!csrfToken) {
      show("error", "缺少 CSRF 令牌，请刷新页面后重试。");
      return;
    }
    submit.disabled = true;
    submit.textContent = mode ? "注册中…" : "登录中…";
    try {
      const response = await fetch(mode ? "/v1/auth/register" : "/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
        credentials: "same-origin",
        body: JSON.stringify({ email: email.value, password: password.value }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        submit.disabled = false;
        submit.textContent = mode ? "注册" : "登录";
        let message = data.message;
        if (response.status === 422) {
          const detail = data.detail;
          message = Array.isArray(detail)
            ? `输入有误：${detail.map((i) => i.msg).filter(Boolean).join("；")}`
            : String(detail || "输入有误");
          if (Array.isArray(detail)) {
            detail.forEach((item) => {
              if (item.loc?.includes("password")) password.setAttribute("aria-invalid", "true");
              if (item.loc?.includes("email")) email.setAttribute("aria-invalid", "true");
            });
          }
        }
        show("error", message || "请求失败，请稍后重试。");
        return;
      }
      location.href = mode ? "/login?registered=1" : (data.user.is_admin ? "/admin" : "/keys");
    } catch (error) {
      submit.disabled = false;
      submit.textContent = mode ? "注册" : "登录";
      show("error", "无法连接服务，请确认服务已启动。");
    }
  });

void initBranding();
submit.disabled = true;
ensureCsrf().then(() => { submit.disabled = false; }).catch(error => show("error", error.message));
