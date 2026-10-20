<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { api } from "../../api/client";
import type { ApiKey, AuditEvent, OffsetPage, User } from "../../api/types";
import { fmtTime } from "../../shared/lib/format.js";
import PageHeading from "../../components/PageHeading.vue";
import Notice from "../../components/Notice.vue";
import Modal from "../../components/Modal.vue";
import OffsetPager from "../../components/OffsetPager.vue";
type List = "users" | "keys" | "audit";
interface ListState {
  page: number;
  total: number;
  more: boolean;
  ready: boolean;
  busy: boolean;
  version: number;
  error: string;
}
const initial = (): ListState => ({
  page: 1,
  total: 0,
  more: false,
  ready: false,
  busy: false,
  version: 0,
  error: "",
});
const lists = reactive({ users: initial(), keys: initial(), audit: initial() });
const users = ref<User[]>([]),
  keys = ref<ApiKey[]>([]),
  audit = ref<AuditEvent[]>([]),
  selected = ref<User | null>(null);
const filters = reactive({ q: "", status: "" }),
  applied = ref({ ...filters });
interface Operation {
  kind: "status" | "revoke";
  id: string;
  title: string;
  description: string;
  status?: "active" | "disabled";
}
const pending = ref<Operation | null>(null),
  mutating = ref(false),
  reason = ref(""),
  modalError = ref(""),
  feedback = ref("");
const reading = computed(() => Object.values(lists).some((item) => item.busy));
const labels: Record<string, string> = {
  active: "已启用",
  disabled: "已停用",
  revoked: "已撤销",
  deleted: "已删除",
};
const controllers = new Map<List, AbortController>();
async function load(name: List): Promise<boolean> {
  const state = lists[name],
    mine = ++state.version,
    owner = selected.value ? { ...selected.value } : null;
  controllers.get(name)?.abort();
  if (name === "keys" && !owner) {
    state.ready = false;
    state.busy = false;
    keys.value = [];
    return true;
  }
  const controller = new AbortController();
  controllers.set(name, controller);
  state.busy = true;
  state.ready = false;
  state.error = "";
  const params = new URLSearchParams({ page: String(state.page), limit: "20" });
  if (name === "users") {
    if (applied.value.q) params.set("q", applied.value.q);
    if (applied.value.status) params.set("status", applied.value.status);
  }
  const path =
    name === "users"
      ? "/v1/admin/users"
      : name === "audit"
        ? "/v1/admin/audit-events"
        : `/v1/admin/users/${encodeURIComponent(owner!.id)}/api-keys`;
  try {
    const result = await api<OffsetPage<User | ApiKey | AuditEvent>>(
      `${path}?${params}`,
      { signal: controller.signal },
    );
    if (
      mine !== state.version ||
      (name === "keys" && owner!.id !== selected.value?.id)
    )
      return false;
    state.page = result.page;
    state.total = result.total;
    state.more = result.has_more;
    state.ready = true;
    if (name === "users") users.value = result.items as User[];
    else if (name === "keys") keys.value = result.items as ApiKey[];
    else audit.value = result.items as AuditEvent[];
    return true;
  } catch (e) {
    if (mine === state.version && (e as Error).name !== "AbortError")
      state.error = (e as Error).message;
    return false;
  } finally {
    if (mine === state.version) state.busy = false;
  }
}
async function refresh() {
  return Promise.all((["users", "keys", "audit"] as List[]).map(load));
}
function apply(reset = false) {
  if (reset) Object.assign(filters, { q: "", status: "" });
  applied.value = { q: filters.q.trim(), status: filters.status };
  lists.users.page = 1;
  void load("users");
}
function viewKeys(user: User) {
  if (mutating.value) return;
  selected.value = { ...user };
  lists.keys.page = 1;
  void load("keys");
}
function turn(name: List, delta: number) {
  if (mutating.value || lists[name].busy || !lists[name].ready) return;
  lists[name].page += delta;
  void load(name);
}
function askStatus(user: User) {
  const status = user.status === "active" ? "disabled" : "active";
  ask({
    kind: "status",
    id: user.id,
    status,
    title: status === "disabled" ? "确认停用用户" : "确认启用用户",
    description: `${user.email}。${status === "disabled" ? "停用后将撤销其现有登录会话，阻止新调用；历史账务保留。" : "启用后用户需重新登录，未撤销的 Key 可恢复使用。"}`,
  });
}
function ask(operation: Operation) {
  if (mutating.value) return;
  pending.value = { ...operation };
  reason.value = "";
  modalError.value = "";
}
async function confirm() {
  if (!pending.value || mutating.value) return;
  if (!reason.value.trim() || reason.value.trim().length > 200) {
    modalError.value = "请填写 1–200 个字符的原因。";
    return;
  }
  const operation = { ...pending.value };
  mutating.value = true;
  modalError.value = "";
  feedback.value = "";
  try {
    const result =
      operation.kind === "status"
        ? await api<{ changed: boolean; user: User }>(
            `/v1/admin/users/${encodeURIComponent(operation.id)}/status`,
            {
              method: "PATCH",
              body: { status: operation.status, reason: reason.value.trim() },
            },
          )
        : await api<{ changed: boolean; user?: User }>(
            `/v1/admin/api-keys/${encodeURIComponent(operation.id)}/revoke`,
            { method: "POST", body: { reason: reason.value.trim() } },
          );
    if (result.user && selected.value?.id === result.user.id)
      selected.value = result.user;
    pending.value = null;
    if (result.changed) lists.audit.page = 1;
    const loaded = await refresh();
    feedback.value =
      (result.changed
        ? "操作已生效并记录审计。"
        : "目标已是该状态，未重复变更或记录审计。") +
      (loaded.every(Boolean)
        ? "列表已刷新。"
        : "部分列表刷新失败，请手动刷新确认。");
  } catch (e) {
    modalError.value = (e as Error).message;
  } finally {
    mutating.value = false;
  }
}
onMounted(refresh);
onBeforeUnmount(() => {
  Object.values(lists).forEach((state) => ++state.version);
  controllers.forEach((controller) => controller.abort());
});
</script>
<template>
  <PageHeading
    title="用户管理"
    subtitle="管理访问权限、查看脱敏密钥，保留每次操作的审计依据。"
    ><button
      id="management-refresh"
      class="button-primary"
      :disabled="mutating || reading"
      @click="refresh"
    >
      刷新列表
    </button></PageHeading
  ><Notice id="management-feedback" :message="feedback" success />
  <form id="users-filter" class="filter-panel" @submit.prevent="apply()">
    <label class="muted"
      >搜索用户<input
        id="users-query"
        v-model="filters.q"
        placeholder="邮箱关键词"
        maxlength="254"
        :disabled="mutating || lists.users.busy" /></label
    ><label class="muted"
      >账号状态<select
        id="users-status"
        v-model="filters.status"
        :disabled="mutating || lists.users.busy"
      >
        <option value="">全部状态</option>
        <option value="active">已启用</option>
        <option value="disabled">已停用</option>
      </select></label
    ><button class="button-primary" :disabled="mutating || lists.users.busy">
      搜索</button
    ><button
      id="users-reset"
      type="button"
      class="button-secondary"
      :disabled="mutating || lists.users.busy"
      @click="apply(true)"
    >
      重置
    </button>
  </form>
  <section class="console-panel">
    <h2>平台用户</h2>
    <Notice :message="lists.users.error" />
    <p id="users-state" role="status" class="muted">
      {{
        lists.users.busy
          ? "正在加载…"
          : lists.users.error
            ? "读取失败：" + lists.users.error
            : "已更新"
      }}
    </p>
    <div class="table-scroll">
      <table class="records-table">
        <thead>
          <tr>
            <th>邮箱</th>
            <th>角色</th>
            <th>状态</th>
            <th>创建时间</th>
            <th>最近登录</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody id="users-rows">
          <tr v-if="!lists.users.ready || !users.length">
            <td colspan="6" class="empty-state">
              {{
                lists.users.busy
                  ? "正在加载…"
                  : lists.users.error
                    ? "数据读取失败，请重试"
                    : "没有符合搜索条件的用户。"
              }}
            </td>
          </tr>
          <tr v-for="user in lists.users.ready ? users : []" :key="user.id">
            <td>{{ user.email }}</td>
            <td>{{ user.is_admin ? "管理员" : "普通用户" }}</td>
            <td>
              <span :class="['status-badge', `status-${user.status}`]">{{
                labels[user.status || ""]
              }}</span>
            </td>
            <td>{{ fmtTime(user.created_at) }}</td>
            <td>{{ fmtTime(user.last_login_at) }}</td>
            <td>
              <div class="admin-row-actions">
                <button
                  data-admin-action="view"
                  class="button-secondary"
                  :aria-pressed="selected?.id === user.id"
                  :disabled="mutating"
                  @click="viewKeys(user)"
                >
                  {{ selected?.id === user.id ? "查看中" : "查看 Key" }}</button
                ><button
                  v-if="!user.is_admin"
                  data-admin-action="user-status"
                  class="button-secondary"
                  :disabled="mutating"
                  @click="askStatus(user)"
                >
                  {{
                    user.status === "active" ? "停用用户" : "启用用户"
                  }}</button
                ><span v-else>管理员受保护</span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <OffsetPager
      name="users"
      :page="lists.users.page"
      :total="lists.users.total"
      :more="lists.users.more"
      :ready="lists.users.ready"
      :busy="mutating || lists.users.busy"
      @change="turn('users', $event)"
    />
  </section>
  <section class="console-panel">
    <h2>用户 API Key</h2>
    <p id="keys-owner" class="muted">
      {{
        selected ? `当前用户：${selected.email}` : "选择用户后查看其脱敏密钥。"
      }}
    </p>
    <Notice :message="lists.keys.error" />
    <p id="keys-state" class="muted" role="status">
      {{
        lists.keys.busy
          ? "正在加载…"
          : lists.keys.error
            ? "读取失败"
            : selected
              ? "已更新"
              : "尚未选择用户"
      }}
    </p>
    <div class="table-scroll">
      <table class="records-table">
        <thead>
          <tr>
            <th>名称</th>
            <th>密钥</th>
            <th>状态</th>
            <th>创建时间</th>
            <th>最近使用</th>
            <th>撤销/删除时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody id="keys-rows">
          <tr v-if="!lists.keys.ready || !keys.length">
            <td colspan="7" class="empty-state">
              {{
                lists.keys.busy
                  ? "正在加载…"
                  : selected
                    ? "此用户暂无可展示的 Key。"
                    : "尚未选择用户"
              }}
            </td>
          </tr>
          <tr v-for="key in lists.keys.ready ? keys : []" :key="key.id">
            <td>{{ key.name }}</td>
            <td>{{ key.display }}</td>
            <td>{{ labels[key.status] }}</td>
            <td>{{ fmtTime(key.created_at) }}</td>
            <td>{{ fmtTime(key.last_used_at) }}</td>
            <td>{{ fmtTime(key.deleted_at || key.revoked_at) }}</td>
            <td>
              <button
                v-if="key.status === 'active'"
                data-admin-action="revoke"
                class="button-secondary button-danger"
                :disabled="mutating"
                @click="
                  ask({
                    kind: 'revoke',
                    id: key.id,
                    title: '确认撤销 Key',
                    description: `将撤销 ${selected?.email} 的 ${key.display}，不可恢复，历史账务保留。`,
                  })
                "
              >
                撤销 Key</button
              ><span v-else>无需操作</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <OffsetPager
      name="keys"
      :page="lists.keys.page"
      :total="lists.keys.total"
      :more="lists.keys.more"
      :ready="lists.keys.ready"
      :busy="mutating || lists.keys.busy"
      @change="turn('keys', $event)"
    />
  </section>
  <section class="console-panel">
    <h2>管理操作审计</h2>
    <Notice :message="lists.audit.error" />
    <p id="audit-state" class="muted" role="status">
      {{
        lists.audit.busy
          ? "正在加载…"
          : lists.audit.error
            ? "读取失败"
            : "已更新"
      }}
    </p>
    <div class="table-scroll">
      <table class="records-table">
        <thead>
          <tr>
            <th>时间（UTC）</th>
            <th>操作人</th>
            <th>目标用户</th>
            <th>操作</th>
            <th>状态变更</th>
            <th>原因</th>
            <th>目标 Key</th>
          </tr>
        </thead>
        <tbody id="audit-rows">
          <tr v-if="!lists.audit.ready || !audit.length">
            <td colspan="7" class="empty-state">
              {{ lists.audit.busy ? "正在加载…" : "尚无管理操作审计记录。" }}
            </td>
          </tr>
          <tr v-for="item in lists.audit.ready ? audit : []" :key="item.id">
            <td>{{ fmtTime(item.created_at) }}</td>
            <td>{{ item.actor_email }}</td>
            <td>{{ item.target_email }}</td>
            <td>
              {{
                item.action === "user.status_changed"
                  ? "用户状态变更"
                  : "撤销 Key"
              }}
            </td>
            <td>
              {{ labels[item.previous_status] || item.previous_status }} →
              {{ labels[item.new_status] || item.new_status }}
            </td>
            <td class="admin-audit-reason">{{ item.reason }}</td>
            <td>{{ item.target_key_id || "—" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <OffsetPager
      name="audit"
      :page="lists.audit.page"
      :total="lists.audit.total"
      :more="lists.audit.more"
      :ready="lists.audit.ready"
      :busy="mutating || lists.audit.busy"
      @change="turn('audit', $event)"
    />
  </section>
  <Modal
    v-if="pending"
    id="management-dialog"
    :title="pending.title"
    :busy="mutating"
    @close="pending = null"
    ><p class="muted">{{ pending.description }}</p>
    <Notice :message="modalError" />
    <form id="management-form" @submit.prevent="confirm">
      <label class="field"
        >操作原因<textarea
          id="management-reason"
          v-model="reason"
          minlength="1"
          maxlength="200"
          required
          autofocus
          :disabled="mutating"
        />
      </label>
      <div class="modal-actions">
        <button
          id="management-cancel"
          type="button"
          class="button-secondary"
          :disabled="mutating"
          @click="pending = null"
        >
          取消</button
        ><button
          id="management-confirm"
          class="button-primary"
          :disabled="mutating"
        >
          {{ mutating ? "正在提交…" : pending.title }}
        </button>
      </div>
    </form></Modal
  >
</template>
