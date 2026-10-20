<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { api } from "../../api/client";
import { query } from "../../api/query";
import type {
  ApiKey,
  CallRow,
  ChargeRow,
  CursorPage,
  KeysResponse,
  Summary,
} from "../../api/types";
import { fmtInt, fmtTime, fmtAmount, fmtMs } from "../../shared/lib/format.js";
import PageHeading from "../../components/PageHeading.vue";
import Metrics from "../../components/Metrics.vue";
import Notice from "../../components/Notice.vue";
import TrendChart from "../../components/TrendChart.vue";
const route = useRoute();
const billing = computed(() => route.path === "/billing"),
  prefix = computed(() => (billing.value ? "/v1/billing" : "/v1/usage"));
const filters = reactive({
  from: "",
  to: "",
  api_key_id: "",
  endpoint: "",
  limit: 20,
});
const applied = ref({ ...filters });
const keys = ref<ApiKey[]>([]),
  summary = ref<Summary | null>(null),
  page = ref<CursorPage<CallRow | ChargeRow> | null>(null);
const error = ref(""),
  busy = ref(false),
  index = ref(0),
  cursors = ref([""]);
let controller: AbortController | undefined,
  version = 0;
async function load(reset = false) {
  if (reset) {
    applied.value = { ...filters };
    index.value = 0;
    cursors.value = [""];
  }
  controller?.abort();
  controller = new AbortController();
  const mine = ++version;
  const summaryQuery = query(applied.value);
  const pageQuery = query({
    ...applied.value,
    cursor: cursors.value[index.value],
  });
  busy.value = true;
  error.value = "";
  try {
    const [totals, rows] = await Promise.all([
      api<Summary>(`${prefix.value}/summary${summaryQuery}`, {
        signal: controller.signal,
      }),
      api<CursorPage<CallRow | ChargeRow>>(
        `${prefix.value}/${billing.value ? "charges" : "calls"}${pageQuery}`,
        { signal: controller.signal },
      ),
    ]);
    if (mine !== version) return;
    summary.value = totals;
    page.value = rows;
    if (rows.has_more && rows.next_cursor)
      cursors.value[index.value + 1] = rows.next_cursor;
  } catch (e) {
    if (mine === version && (e as Error).name !== "AbortError") {
      error.value = (e as Error).message;
      page.value = null;
      summary.value = null;
    }
  } finally {
    if (mine === version) busy.value = false;
  }
}
const metrics = computed(() => {
  const t = summary.value?.totals;
  return billing.value
    ? [
        {
          label: "计费输入 Token",
          value: fmtInt(t?.billable_tokens),
          id: "stat-tokens",
        },
        {
          label: "费用合计",
          value: "¥ " + fmtAmount(t?.charged_amount_yuan),
          id: "stat-amount",
        },
        {
          label: "费用记录",
          value: fmtInt(t?.charge_count),
          id: "stat-charges",
        },
        { label: "调用总数", value: fmtInt(t?.calls_total), id: "stat-calls" },
      ]
    : [
        { label: "调用总数", value: fmtInt(t?.calls_total), id: "stat-calls" },
        {
          label: "成功调用",
          value: fmtInt(t?.calls_succeeded),
          id: "stat-succeeded",
        },
        {
          label: "失败调用",
          value: fmtInt(t?.calls_failed),
          id: "stat-failed",
        },
        {
          label: "输入 Token",
          value: fmtInt(t?.input_tokens),
          id: "stat-tokens",
        },
      ];
});
function changePage(delta: number) {
  if (busy.value) return;
  index.value += delta;
  void load();
}
onMounted(async () => {
  try {
    keys.value = (await api<KeysResponse>("/v1/api-keys")).items;
  } catch (e) {
    error.value = (e as Error).message;
  }
  await load(true);
});
onBeforeUnmount(() => {
  ++version;
  controller?.abort();
});
</script>
<template>
  <PageHeading
    :title="billing ? '费用统计' : '调用统计'"
    :subtitle="
      billing
        ? '每一笔费用，都有可追溯的调用依据。'
        : '了解模型使用情况，定位每一次调用。'
    "
  />
  <form class="filter-panel" @submit.prevent="load(true)">
    <label class="muted"
      >开始日期（UTC）<input
        id="date-from"
        v-model="filters.from"
        type="date" /></label
    ><label class="muted"
      >结束日期（含当天）<input
        id="date-to"
        v-model="filters.to"
        type="date" /></label
    ><label class="muted"
      >API Key<select id="key-filter" v-model="filters.api_key_id">
        <option value="">全部密钥</option>
        <option v-for="key in keys" :key="key.id" :value="key.id">
          {{ key.name || "未命名" }} · {{ key.display
          }}{{ key.status === "revoked" ? "（已撤销）" : "" }}
        </option>
      </select></label
    ><label class="muted"
      >接口<select id="endpoint-filter" v-model="filters.endpoint">
        <option value="">全部接口</option>
        <option
          v-for="endpoint in [
            '/v1/predict',
            '/v1/customer-service/analyze',
            '/v1/chat/completions',
          ]"
          :key="endpoint"
        >
          {{ endpoint }}
        </option>
      </select></label
    ><label class="muted"
      >每页<select id="page-size" v-model="filters.limit" @change="load(true)">
        <option :value="20">20 条</option>
        <option :value="50">50 条</option>
        <option :value="100">100 条</option>
      </select></label
    ><button id="apply" class="button-primary" :disabled="busy">
      {{ busy ? "查询中…" : "应用筛选" }}
    </button>
  </form>
  <Notice id="error" :message="error" /><Metrics :items="metrics" />
  <p v-if="billing" class="safety-notice" id="price-banner">
    {{
      summary?.price?.version
        ? `当前单价 ¥${summary.price.unit_price_yuan} / ${fmtInt(summary.price.unit_tokens)} 输入 Token（价格版本 ${summary.price.version}，币种 ${summary.price.currency}）`
        : "暂无适用价格规则。"
    }}
  </p>
  <p class="muted">
    <span id="range">{{
      summary
        ? `${fmtTime(summary.range.from)} 至 ${fmtTime(summary.range.to)}（UTC）`
        : "等待查询"
    }}</span>
    · 待确认计费
    <span id="pending">{{ fmtInt(summary?.totals.billing_pending_count) }}</span
    ><template v-if="!billing">
      · 进行中 {{ fmtInt(summary?.totals.calls_in_progress) }}</template
    >
  </p>
  <section class="console-panel">
    <TrendChart
      :series="summary?.series || []"
      :field="billing ? 'amount_yuan' : 'succeeded'"
      :secondary="!billing"
      :label="billing ? '每日费用（元）' : '每日调用趋势'"
    />
  </section>
  <section class="console-panel">
    <h2>{{ billing ? "费用明细" : "调用记录" }}</h2>
    <div class="table-scroll">
      <table class="records-table">
        <thead>
          <tr>
            <th>请求 ID</th>
            <th>API Key</th>
            <template v-if="billing"
              ><th>计费 Token</th>
              <th>计费单位 / 单价</th>
              <th>价格版本</th>
              <th>费用（元）</th></template
            ><template v-else
              ><th>接口</th>
              <th>时间（UTC）</th>
              <th>状态</th>
              <th>输入 Token</th>
              <th>耗时</th></template
            >
          </tr>
        </thead>
        <tbody id="rows">
          <tr v-if="busy || !page?.items.length">
            <td :colspan="billing ? 6 : 7" class="empty-state">
              {{
                busy
                  ? "加载中…"
                  : error
                    ? "数据读取失败，请重试。"
                    : "所选范围内暂无记录。"
              }}
            </td>
          </tr>
          <tr v-for="row in page?.items || []" v-else :key="row.request_id">
            <td class="font-mono" :title="row.request_id">
              {{ row.request_id.slice(0, 8) }}
            </td>
            <td>{{ row.api_key }}</td>
            <template v-if="'billable_tokens' in row"
              ><td>{{ fmtInt(row.billable_tokens) }}</td>
              <td>
                {{ fmtInt(row.unit_tokens) }} / ¥{{ row.unit_price_yuan }}
              </td>
              <td>{{ row.pricing_version }}</td>
              <td>¥ {{ fmtAmount(row.amount_yuan) }}</td></template
            ><template v-else
              ><td>{{ row.endpoint }}</td>
              <td>{{ fmtTime(row.started_at) }}</td>
              <td>
                <span :class="['status-badge', `status-${row.status}`]">{{
                  row.status
                }}</span>
              </td>
              <td>
                {{ row.input_tokens === null ? "—" : fmtInt(row.input_tokens) }}
              </td>
              <td>{{ fmtMs(row.duration_ms) }}</td></template
            >
          </tr>
        </tbody>
      </table>
    </div>
    <div class="pagination">
      <span id="page-info"
        >第 {{ index + 1 }} 页 · 共
        {{
          fmtInt(
            billing
              ? summary?.totals.charge_count
              : summary?.totals.calls_total,
          )
        }}
        条</span
      >
      <div>
        <button
          id="prev"
          class="button-secondary"
          :disabled="busy || index === 0"
          @click="changePage(-1)"
        >
          上一页</button
        ><button
          id="next"
          class="button-secondary"
          :disabled="busy || !page?.has_more || !page.next_cursor"
          @click="changePage(1)"
        >
          下一页
        </button>
      </div>
    </div>
  </section>
  <p v-if="billing && summary?.price" class="muted" id="price-formula">
    费用 = 计费输入 Token ÷ {{ fmtInt(summary.price.unit_tokens) }} × ¥{{
      summary.price.unit_price_yuan
    }}，保留 6 位小数。计费策略
    {{
      summary.price.billing_policy_version
    }}。当前价格只作展示，历史费用沿调用当时的价格。
  </p>
</template>
