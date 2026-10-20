<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { api } from "../../api/client";
import type { Branding, Connection, ConnectionResponse } from "../../api/types";
import { applyBranding } from "../../composables/branding";
import Notice from "../../components/Notice.vue";
import PageHeading from "../../components/PageHeading.vue";
const form = reactive({ name: "", description: "" });
const savedLogo = ref(""),
  logoChange = ref<string | null>(null),
  file = ref<HTMLInputElement>();
const previewLogo = computed(() =>
  logoChange.value === null ? savedLogo.value : logoChange.value,
);
const ready = ref(false),
  saving = ref(false),
  reading = ref(false),
  error = ref(""),
  status = ref("");
let fileVersion = 0;
const connection = reactive<Connection>({
  base_url: "http://127.0.0.1:11434/v1",
  model: "",
  timeout_seconds: 120,
  enabled: false,
});
const connectionReady = ref(false),
  connectionBusy = ref(false),
  connectionError = ref(""),
  connectionStatus = ref(""),
  metadata = ref<ConnectionResponse>();
async function loadBrand() {
  ready.value = false;
  error.value = "";
  try {
    const result = await api<{ branding: Branding }>("/v1/platform/branding");
    Object.assign(form, result.branding);
    savedLogo.value = result.branding.logo_url;
    ready.value = true;
    status.value = "配置已加载";
  } catch (e) {
    error.value = (e as Error).message;
    status.value = "读取配置失败，请重试";
  }
}
function resetLogo() {
  ++fileVersion;
  logoChange.value = "";
  reading.value = false;
  if (file.value) file.value.value = "";
  status.value = "已选择默认 Logo，保存后生效";
}
function upload(event: Event) {
  const input = event.target as HTMLInputElement,
    selected = input.files?.[0],
    version = ++fileVersion;
  error.value = "";
  reading.value = false;
  if (!selected) return;
  if (
    !["image/png", "image/jpeg", "image/webp"].includes(selected.type) ||
    selected.size > 2 * 1024 * 1024
  ) {
    error.value = "请选择不超过 2 MB 的 PNG、JPEG 或 WebP 图片";
    input.value = "";
    return;
  }
  reading.value = true;
  const reader = new FileReader();
  reader.onload = () => {
    if (version === fileVersion) {
      logoChange.value = String(reader.result);
      reading.value = false;
      status.value = "Logo 已选择，保存后生效";
    }
  };
  reader.onerror = () => {
    if (version === fileVersion) {
      reading.value = false;
      error.value = "无法读取图片，请重新选择";
    }
  };
  reader.readAsDataURL(selected);
}
async function saveBrand() {
  if (!ready.value || reading.value || saving.value) return;
  saving.value = true;
  error.value = "";
  status.value = "保存中…";
  try {
    const result = await api<{ branding: Branding }>("/v1/admin/settings", {
      method: "PUT",
      body: {
        name: form.name,
        description: form.description,
        logo_data_url: logoChange.value,
      },
    });
    Object.assign(form, result.branding);
    savedLogo.value = result.branding.logo_url;
    logoChange.value = null;
    if (file.value) file.value.value = "";
    applyBranding(result.branding);
    status.value = "配置已保存";
  } catch (e) {
    error.value = (e as Error).message;
    status.value = "保存失败，修改内容已保留";
  } finally {
    saving.value = false;
  }
}
async function loadConnection() {
  connectionReady.value = false;
  connectionError.value = "";
  try {
    metadata.value = await api<ConnectionResponse>(
      "/v1/admin/model-connection",
    );
    if (metadata.value.connection)
      Object.assign(connection, metadata.value.connection);
    connectionReady.value = true;
    connectionStatus.value = metadata.value.connection
      ? "连接配置已加载。"
      : "尚未配置上游，填写后先测试连接。";
  } catch (e) {
    connectionError.value = (e as Error).message;
    connectionStatus.value = "配置读取失败，请重试";
  }
}
const connectionForm = ref<HTMLFormElement>();
async function connectionAction(test = false) {
  if (
    !connectionReady.value ||
    connectionBusy.value ||
    !connectionForm.value?.reportValidity()
  )
    return;
  connectionBusy.value = true;
  connectionError.value = "";
  connectionStatus.value = test ? "测试中，请等待上游响应…" : "保存中…";
  try {
    if (test) {
      const result = await api<{ model: string }>(
        "/v1/admin/model-connection/test",
        { method: "POST", body: { ...connection } },
      );
      connectionStatus.value = `连接成功，模型 ${result.model} 可用；尚未保存修改。`;
    } else {
      metadata.value = await api<ConnectionResponse>(
        "/v1/admin/model-connection",
        { method: "PUT", body: { ...connection } },
      );
      connectionStatus.value = "模型连接已保存，新请求立即使用新配置。";
    }
  } catch (e) {
    connectionError.value = (e as Error).message;
    connectionStatus.value = "操作失败，输入内容已保留。";
  } finally {
    connectionBusy.value = false;
  }
}
onMounted(() => Promise.all([loadBrand(), loadConnection()]));
onBeforeUnmount(() => { ++fileVersion; });
</script>
<template>
  <PageHeading title="平台配置" subtitle="定义你的品牌，连接自部署模型。" />
  <div class="two-panels">
    <section class="console-panel">
      <h2>品牌设置</h2>
      <Notice id="error" :message="error" />
      <form id="settings-form" @submit.prevent="saveBrand">
        <fieldset :disabled="saving || !ready">
          <label class="field"
            >平台名称<input
              id="platform-name"
              v-model="form.name"
              maxlength="60"
              required /></label
          ><label class="field"
            >平台简介<textarea
              id="platform-description"
              v-model="form.description"
              maxlength="200"
            /></label
          ><label class="field"
            >Logo 图片<input
              id="platform-logo"
              ref="file"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              @change="upload"
          /></label>
          <p class="muted">
            支持 PNG、JPEG、WebP，不超过 2 MB。服务端会重新验证图片。
          </p>
          <button
            id="reset-logo"
            class="button-secondary"
            type="button"
            @click="resetLogo"
          >
            使用默认 Logo
          </button>
          <div class="modal-actions">
            <button
              id="save-settings"
              class="button-primary"
              :disabled="reading || saving || !ready"
            >
              {{ saving ? "保存中…" : "保存配置" }}
            </button>
          </div>
        </fieldset>
      </form>
      <p id="settings-status" role="status" class="muted">{{ status }}</p>
      <button v-if="!ready" class="button-secondary" @click="loadBrand">
        重试读取品牌
      </button>
    </section>
    <section class="console-panel">
      <h2>实时预览</h2>
      <div class="brand-preview">
        <img
          v-if="previewLogo"
          id="preview-logo"
          class="logo-preview mx-auto"
          :src="previewLogo"
          alt="Logo 预览"
        /><span v-else id="preview-default" aria-hidden="true" class="text-4xl"
          >◈</span
        >
        <h3 id="preview-name" class="text-3xl font-semibold mt-4">
          {{ form.name || "平台名称" }}
        </h3>
        <p id="preview-description" class="text-sm mt-3">
          {{ form.description }}
        </p>
      </div>
      <p class="muted mt-4">预览不代表已保存。名称和简介以纯文本显示。</p>
    </section>
  </div>
  <section class="console-panel">
    <h2>自部署模型连接</h2>
    <Notice id="connection-error" :message="connectionError" />
    <p id="model-runtime" class="muted">
      {{
        metadata?.runtime === "external"
          ? "运行模式：仅外部模型，不加载本地 Laya。"
          : "运行模式：本地 Laya + 外部模型连接。"
      }}
    </p>
    <p id="model-credential" class="muted">
      {{
        metadata?.credential_configured
          ? "服务器已配置上游凭据（不会在页面显示）。"
          : "服务器未配置上游凭据，适用于不要求认证的本地服务。"
      }}
    </p>
    <form
      id="connection-form"
      ref="connectionForm"
      @submit.prevent="connectionAction()"
    >
      <fieldset :disabled="connectionBusy || !connectionReady">
        <div class="two-panels">
          <label class="field"
            >Base URL<input
              id="model-base-url"
              v-model.trim="connection.base_url"
              type="url"
              maxlength="512"
              required
              placeholder="http://127.0.0.1:11434/v1" /></label
          ><label class="field"
            >模型名称<input
              id="model-name"
              v-model.trim="connection.model"
              maxlength="64"
              required /></label
          ><label class="field"
            >超时（秒）<input
              id="model-timeout"
              v-model.number="connection.timeout_seconds"
              type="number"
              min="1"
              max="300"
              required /></label
          ><label class="field flex items-center gap-3"
            ><input
              id="model-enabled"
              v-model="connection.enabled"
              type="checkbox"
              class="w-5"
            />启用模型连接</label
          >
        </div>
        <div class="modal-actions">
          <button
            id="test-connection"
            type="button"
            class="button-secondary"
            @click="connectionAction(true)"
          >
            测试连接</button
          ><button id="save-connection" class="button-primary">
            保存模型连接
          </button>
        </div>
      </fieldset>
    </form>
    <p id="connection-status" role="status" class="muted">
      {{ connectionStatus }}
    </p>
    <button
      v-if="!connectionReady"
      class="button-secondary"
      @click="loadConnection"
    >
      重试读取连接
    </button>
  </section>
</template>
