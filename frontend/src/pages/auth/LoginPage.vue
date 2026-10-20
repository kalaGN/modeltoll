<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, ensureCsrf } from "../../api/client";
import type { User } from "../../api/types";
import { branding } from "../../composables/branding";
import { currentUser } from "../../composables/session";
import Notice from "../../components/Notice.vue";
const route = useRoute(),
  router = useRouter();
const register = computed(
  () => route.path === "/register" || route.query.mode === "register",
);
const email = ref(""),
  password = ref(""),
  reveal = ref(false),
  busy = ref(false),
  ready = ref(false);
const error = ref(String(route.query.error || ""));
onMounted(async () => {
  try {
    await ensureCsrf();
    ready.value = true;
  } catch (e) {
    error.value = (e as Error).message;
  }
});
async function submit() {
  if (busy.value || !ready.value) return;
  error.value = "";
  busy.value = true;
  try {
    const result = await api<{ user: User }>(
      register.value ? "/v1/auth/register" : "/v1/auth/login",
      {
        method: "POST",
        body: { email: email.value, password: password.value },
      },
    );
    password.value = "";
    if (register.value) await router.push("/login?registered=1");
    else {
      currentUser.value = result.user;
      await router.push(result.user.is_admin ? "/admin" : "/keys");
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : "无法连接服务，请稍后重试。";
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="login-page">
    <div class="login-layout">
      <section class="login-brand">
        <RouterLink to="/login" class="brand"
          ><img
            v-if="branding.logo_url"
            :src="branding.logo_url"
            alt=""
            class="brand-mark"
          /><span v-else class="brand-mark" aria-hidden="true">◈</span
          ><span
            ><strong>{{ branding.name }}</strong
            ><small>{{ branding.description }}</small></span
          ></RouterLink
        >
        <div class="login-statement">
          <h1>让每一次调用，<br />都清晰<span>可见。</span></h1>
          <p>从一枚密钥开始。<br />连接模型，掌握用量，看清成本。</p>
        </div>
        <div class="signal-art" aria-hidden="true">
          <svg viewBox="0 0 600 240" fill="none">
            <path
              d="M0 180h100l60-120 80 150 75-170 70 130h215"
              stroke="currentColor"
              stroke-width="2"
            />
            <circle cx="315" cy="40" r="12" fill="currentColor" />
            <path
              d="M0 220h600M0 100h600M100 0v240M300 0v240M500 0v240"
              stroke="currentColor"
              opacity=".13"
            />
          </svg>
        </div>
        <div class="login-capabilities">
          <span><b>01</b> 密钥管理</span><span><b>02</b> 调用追踪</span
          ><span><b>03</b> 费用明细</span>
        </div>
      </section>
      <section class="login-form-panel">
        <div class="w-full max-w-[380px]">
          <h2 id="title" class="text-center text-[34px] font-bold">
            {{ register ? "创建账号" : "欢迎回来" }}
          </h2>
          <p class="mb-10 mt-3.5 text-center text-slate-500">
            {{
              register
                ? "注册后即可登录模型 API 平台。"
                : `使用邮箱和密码登录 ${branding.name}。`
            }}
          </p>
          <Notice :message="error" /><Notice
            v-if="route.query.registered"
            message="注册成功，请使用新账号登录。"
            success
          />
          <form id="form" @submit.prevent="submit">
            <label class="field"
              >邮箱地址<input
                id="email"
                v-model="email"
                type="email"
                autocomplete="username"
                placeholder="name@example.com"
                required
                :disabled="busy" /></label
            ><label class="field"
              >密码
              <div class="password-field">
                <input
                  id="password"
                  v-model="password"
                  :type="reveal ? 'text' : 'password'"
                  :autocomplete="register ? 'new-password' : 'current-password'"
                  minlength="8"
                  maxlength="128"
                  required
                  :disabled="busy"
                /><button
                  id="reveal"
                  type="button"
                  :aria-label="reveal ? '隐藏密码' : '显示密码'"
                  :aria-pressed="reveal"
                  @click="reveal = !reveal"
                >
                  {{ reveal ? "隐藏" : "显示" }}
                </button>
              </div></label
            >
            <p class="muted text-sm mb-5">
              {{
                register
                  ? "密码长度需为 8–128 个字符。"
                  : "请使用已有账号登录。"
              }}
            </p>
            <button id="submit" class="login-submit" :disabled="busy || !ready">
              {{ busy ? "提交中…" : register ? "注册" : "登录" }}
            </button>
          </form>
          <p class="text-center mt-6 text-sm muted">
            <template v-if="register"
              >已有账号？<RouterLink to="/login">直接登录</RouterLink></template
            ><template v-else
              >还没有账号？<RouterLink to="/register"
                >创建账号</RouterLink
              ></template
            >
          </p>
        </div>
      </section>
    </div>
  </div>
</template>
