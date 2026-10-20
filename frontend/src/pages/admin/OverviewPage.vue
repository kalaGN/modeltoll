<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { api } from "../../api/client";
import type { Point, Range } from "../../api/types";
import { fmtInt, fmtAmount } from "../../shared/lib/format.js";
import PageHeading from "../../components/PageHeading.vue";
import Metrics from "../../components/Metrics.vue";
import Notice from "../../components/Notice.vue";
import TrendChart from "../../components/TrendChart.vue";
interface Overview {
  range: Range;
  totals: {
    users: number;
    active_keys: number;
    calls: number;
    amount_yuan: string;
  };
  series: Point[];
}
const now = new Date(),
  start = new Date(now.getTime() - 6 * 86400000);
const dates = reactive({
  from: start.toISOString().slice(0, 10),
  to: now.toISOString().slice(0, 10),
});
const data = ref<Overview | null>(null),
  error = ref(""),
  busy = ref(false);
let controller: AbortController | undefined;
const series = computed(() => {
  if (!data.value) return [];
  const indexed = new Map(data.value.series.map((row) => [row.date, row]));
  const first = new Date(data.value.range.from),
    upper = new Date(data.value.range.to),
    result: Point[] = [];
  first.setUTCHours(0, 0, 0, 0);
  for (
    let day = first;
    day < upper && result.length < 367;
    day = new Date(day.getTime() + 86400000)
  ) {
    const date = day.toISOString().slice(0, 10);
    result.push(indexed.get(date) || { date, calls: 0, amount_yuan: "0" });
  }
  return result;
});
async function load() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  controller = new AbortController();
  try {
    data.value = await api<Overview>(
      "/v1/admin/overview?" + new URLSearchParams(dates),
      { signal: controller.signal },
    );
  } catch (e) {
    if ((e as Error).name !== "AbortError") {
      error.value = (e as Error).message;
      data.value = null;
    }
  } finally {
    busy.value = false;
  }
}
onMounted(load);
onBeforeUnmount(() => controller?.abort());
</script>
<template>
  <PageHeading
    title="平台总览"
    subtitle="从整体用量到每日费用，掌握模型服务运行情况。"
  />
  <form id="overview-filter" class="filter-panel" @submit.prevent="load">
    <label class="muted"
      >开始日期（UTC）<input
        id="admin-from"
        v-model="dates.from"
        type="date"
        required /></label
    ><label class="muted"
      >结束日期（含当天）<input
        id="admin-to"
        v-model="dates.to"
        type="date"
        required /></label
    ><button id="admin-refresh" class="button-primary" :disabled="busy">
      {{ busy ? "加载中…" : "刷新总览" }}</button
    ><span id="overview-state" role="status" class="muted">{{
      busy
        ? "加载中…"
        : error
          ? "读取失败，请重试"
          : data?.totals.calls
            ? "已更新"
            : "所选时间暂无调用"
    }}</span>
  </form>
  <Notice id="error" :message="error" /><Metrics
    :items="[
      {
        label: '平台用户',
        value: data ? fmtInt(data.totals.users) : '—',
        id: 'stat-users',
      },
      {
        label: '可用密钥',
        value: data ? fmtInt(data.totals.active_keys) : '—',
        id: 'stat-keys',
      },
      {
        label: '调用次数',
        value: data ? fmtInt(data.totals.calls) : '—',
        id: 'stat-calls',
      },
      {
        label: '费用合计',
        value: data ? '¥ ' + fmtAmount(data.totals.amount_yuan) : '—',
        id: 'stat-amount',
      },
    ]"
  />
  <div class="two-panels">
    <section class="console-panel">
      <TrendChart :series="series" field="calls" label="每日调用次数" />
    </section>
    <section class="console-panel">
      <TrendChart :series="series" field="amount_yuan" label="每日费用（元）" />
    </section>
  </div>
  <section class="console-panel">
    <h2>每日明细</h2>
    <div class="table-scroll">
      <table class="records-table">
        <thead>
          <tr>
            <th>日期（UTC）</th>
            <th>调用次数</th>
            <th>费用（元）</th>
          </tr>
        </thead>
        <tbody id="admin-daily">
          <tr v-for="row in series" :key="row.date">
            <td>{{ row.date }}</td>
            <td>{{ fmtInt(row.calls) }}</td>
            <td>¥ {{ fmtAmount(row.amount_yuan) }}</td>
          </tr>
          <tr v-if="!series.length">
            <td colspan="3" class="empty-state">
              {{ error ? "数据读取失败" : "暂无数据" }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
