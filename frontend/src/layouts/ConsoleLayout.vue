<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { branding } from "../composables/branding";
import { currentUser, logout } from "../composables/session";
import Notice from "../components/Notice.vue";
const route = useRoute(),
  router = useRouter();
const admin = computed(() => route.path.startsWith("/admin"));
const links = computed(() =>
  admin.value
    ? [
        ["/admin", "平台总览"],
        ["/admin/settings", "平台配置"],
        ["/admin/users", "用户管理"],
      ]
    : [
        ["/keys", "API Key"],
        ["/usage", "调用统计"],
        ["/billing", "费用统计"],
      ],
);
const error = ref(""),
  busy = ref(false);
async function signOut() {
  busy.value = true;
  error.value = "";
  try {
    await logout();
    await router.replace("/login");
  } catch (e) {
    error.value = e instanceof Error ? e.message : "退出失败";
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="console-page">
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <div class="console-shell">
      <aside class="console-sidebar">
        <RouterLink class="brand" to="/"
          ><img
            v-if="branding.logo_url"
            class="brand-mark object-contain"
            :src="branding.logo_url"
            alt=""
          /><span v-else class="brand-mark" aria-hidden="true">◈</span
          ><span
            ><strong>{{ branding.name }}</strong
            ><small>{{ branding.description }}</small></span
          ></RouterLink
        >
        <nav class="console-nav" aria-label="主导航">
          <RouterLink
            v-for="[path, label] in links"
            :key="path"
            :to="path!"
            class="nav-link"
            :class="{ 'is-active': route.path === path }"
            >{{ label }}</RouterLink
          >
        </nav>
        <div class="account-panel">
          <div class="min-w-0">
            <span id="account" class="break-all">{{ currentUser?.email }}</span
            ><button id="logout" :disabled="busy" @click="signOut">
              {{ busy ? "退出中…" : "退出登录" }}
            </button>
          </div>
        </div>
      </aside>
      <div class="console-workspace">
        <div class="console-topbar">
          <span>{{ admin ? "平台管理" : "个人控制台" }}</span
          ><RouterLink
            v-if="currentUser?.is_admin"
            :to="admin ? '/keys' : '/admin'"
            class="button-secondary console-switch"
            >{{ admin ? "返回个人控制台" : "切换平台管理" }}</RouterLink
          >
        </div>
        <main id="main-content" class="console-main">
          <Notice :message="error" /><RouterView :key="route.path" />
        </main>
        <footer class="console-footer">
          {{ branding.name }} · 数据和计费由服务端确认
        </footer>
      </div>
    </div>
  </div>
</template>
