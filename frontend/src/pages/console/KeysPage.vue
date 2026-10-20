<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../../api/client";
import type { ApiKey, KeysResponse } from "../../api/types";
import { fmtInt, fmtTime } from "../../shared/lib/format.js";
import PageHeading from "../../components/PageHeading.vue";
import Metrics from "../../components/Metrics.vue";
import Modal from "../../components/Modal.vue";
import Notice from "../../components/Notice.vue";
const data = ref<KeysResponse>({
  items: [],
  summary: { total: 0, active: 0, revoked: 0 },
});
const loading = ref(false),
  busy = ref(false),
  error = ref(""),
  modalError = ref(""),
  name = ref("");
const modal = ref<"create" | "revoke" | "delete" | "secret" | null>(null),
  target = ref<ApiKey | null>(null);
const secret = ref(""),
  example = ref("申请 API Key 后，这里会给出与实际契约一致的调用示例。"),
  copied = ref("复制");
async function load() {
  loading.value = true;
  error.value = "";
  try {
    data.value = await api<KeysResponse>("/v1/api-keys");
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}
function open(
  kind: "create" | "revoke" | "delete",
  item: ApiKey | null = null,
) {
  target.value = item;
  name.value = "";
  modalError.value = "";
  modal.value = kind;
}
function close() {
  if (busy.value) return;
  modal.value = null;
  secret.value = "";
  target.value = null;
}
async function confirm() {
  if (busy.value) return;
  busy.value = true;
  modalError.value = "";
  try {
    if (modal.value === "create") {
      const created = await api<{ secret: string; call_example: string }>(
        "/v1/api-keys",
        { method: "POST", body: { name: name.value.trim() } },
      );
      secret.value = created.secret;
      example.value = created.call_example.replaceAll(
        created.secret,
        "YOUR_API_KEY",
      );
      copied.value = "复制";
      modal.value = "secret";
    } else if (target.value) {
      if (modal.value === "revoke")
        await api(
          `/v1/api-keys/${encodeURIComponent(target.value.id)}/revoke`,
          { method: "POST", body: { confirm: true } },
        );
      else
        await api(`/v1/api-keys/${encodeURIComponent(target.value.id)}`, {
          method: "DELETE",
        });
      modal.value = null;
      target.value = null;
    }
    await load();
  } catch (e) {
    modalError.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
async function copy() {
  try {
    await navigator.clipboard.writeText(secret.value);
    copied.value = "已复制";
  } catch {
    copied.value = "复制失败，请手动选中";
  }
}
onMounted(load);
</script>
<template>
  <PageHeading
    title="API Key 管理"
    subtitle="让每个应用拥有独立凭证，安全连接你的模型。"
    ><button id="create" class="button-primary" @click="open('create')">
      <span>＋</span>申请 API Key
    </button></PageHeading
  ><Notice :message="error" /><Metrics
    :items="[
      {
        label: '密钥总数',
        value: fmtInt(data.summary.total),
        id: 'stat-total',
      },
      {
        label: '可用密钥',
        value: fmtInt(data.summary.active),
        id: 'stat-active',
      },
      {
        label: '已撤销',
        value: fmtInt(data.summary.revoked),
        id: 'stat-revoked',
      },
    ]"
  />
  <p class="safety-notice">
    完整 Key
    仅在创建时显示，请妥善保存。撤销后不可恢复，删除只隐藏已撤销密钥，不影响历史账务。
  </p>
  <section class="console-panel">
    <div class="panel-heading">
      <h2>我的密钥</h2>
      <button class="button-secondary" :disabled="loading" @click="load">
        刷新列表
      </button>
    </div>
    <div class="table-scroll">
      <table class="records-table">
        <thead>
          <tr>
            <th>名称</th>
            <th>API Key</th>
            <th>状态</th>
            <th>创建时间（UTC）</th>
            <th>最近使用</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody id="rows">
          <tr v-if="loading || !data.items.length">
            <td colspan="6" class="empty-state">
              {{ loading ? "加载中…" : "还没有 API Key，点击右上角申请一个。" }}
            </td>
          </tr>
          <tr v-for="item in data.items" v-else :key="item.id">
            <td>{{ item.name || "未命名" }}</td>
            <td class="font-mono">{{ item.display }}</td>
            <td>
              <span :class="['status-badge', `status-${item.status}`]">{{
                item.status === "active" ? "可用" : "已撤销"
              }}</span>
            </td>
            <td>{{ fmtTime(item.created_at) }}</td>
            <td>{{ fmtTime(item.last_used_at) }}</td>
            <td>
              <button
                class="button-secondary button-danger"
                @click="
                  open(item.status === 'active' ? 'revoke' : 'delete', item)
                "
              >
                {{ item.status === "active" ? "撤销" : "删除" }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
  <section class="integration-panel">
    <div class="integration-intro">
      <h2>从一次调用开始</h2>
      <p>使用 Bearer Token 调用模型。示例中的占位符需替换为你自己的 Key。</p>
    </div>
    <div class="integration-code">
      <pre id="example">{{ example }}</pre>
    </div>
  </section>
  <Modal
    v-if="modal"
    :key="modal"
    :id="`${modal}-modal`"
    :title="
      modal === 'create'
        ? '申请 API Key'
        : modal === 'secret'
          ? '请立即保存你的密钥'
          : modal === 'revoke'
            ? '确认撤销'
            : '确认删除'
    "
    :busy="busy || modal === 'secret'"
    @close="close"
    ><Notice :message="modalError" /><template v-if="modal === 'secret'"
      ><p class="muted">完整密钥仅显示本次，关闭后无法再次查看。</p>
      <pre id="secret" class="secret-value">{{ secret }}</pre>
      <div class="modal-actions">
        <button id="copy" class="button-secondary" @click="copy">
          {{ copied }}</button
        ><button id="close" class="button-primary" @click="close">
          我已保存
        </button>
      </div></template
    >
    <form v-else @submit.prevent="confirm">
      <label v-if="modal === 'create'" class="field"
        >密钥名称<input
          id="key-name"
          v-model="name"
          maxlength="64"
          placeholder="例如：生产环境应用"
          autofocus
          :disabled="busy"
      /></label>
      <p v-else class="muted">
        {{ target?.name }} · {{ target?.display }}。{{
          modal === "revoke"
            ? "撤销后不可恢复，历史调用与费用仍会保留。"
            : "将从列表隐藏，历史调用与费用仍会保留。"
        }}
      </p>
      <div class="modal-actions">
        <button
          :id="`${modal}-cancel`"
          type="button"
          class="button-secondary"
          :disabled="busy"
          @click="close"
        >
          取消</button
        ><button
          :id="`${modal}-confirm`"
          class="button-primary"
          :disabled="busy"
        >
          {{
            busy
              ? "提交中…"
              : modal === "create"
                ? "创建"
                : modal === "revoke"
                  ? "确认撤销"
                  : "确认删除"
          }}
        </button>
      </div>
    </form></Modal
  >
</template>
