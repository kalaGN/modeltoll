<script setup lang="ts">
import { computed } from "vue";
import type { Point } from "../api/types";
const props = defineProps<{
  series: Point[];
  field: "calls" | "succeeded" | "amount_yuan";
  label: string;
  secondary?: boolean;
}>();
const highest = computed(() =>
  Math.max(
    1,
    ...props.series.map((row) => Number(row[props.field] || 0)),
    ...(props.secondary
      ? props.series.map((row) => Number(row.failed || 0))
      : []),
  ),
);
function points(field: "calls" | "succeeded" | "amount_yuan" | "failed") {
  return props.series
    .map(
      (row, i) =>
        `${30 + (i * 730) / Math.max(1, props.series.length - 1)},${165 - (Number(row[field] || 0) / highest.value) * 130}`,
    )
    .join(" ");
}
</script>
<template>
  <figure class="trend">
    <figcaption>
      {{ label
      }}<span v-if="secondary" class="muted"> · 绿色成功 / 红色失败</span>
    </figcaption>
    <p v-if="!series.length" class="empty-state">所选时间暂无数据</p>
    <svg v-else viewBox="0 0 800 210" role="img" :aria-label="label">
      <path d="M30 35H770M30 100H770M30 165H770" stroke="#e6e9df" />
      <text x="0" y="30" font-size="11">{{ highest }}</text>
      <polyline
        :points="points(field)"
        fill="none"
        stroke="#344b2d"
        stroke-width="3"
      />
      <polyline
        v-if="secondary"
        :points="points('failed')"
        fill="none"
        stroke="#b42318"
        stroke-width="2"
      />
      <g v-for="(row, i) in series" :key="row.date">
        <circle
          :cx="30 + (i * 730) / Math.max(1, series.length - 1)"
          :cy="165 - (Number(row[field] || 0) / highest) * 130"
          r="4"
          fill="#87ac24"
        >
          <title>{{ row.date }}：{{ row[field] || 0 }}</title>
        </circle>
      </g>
      <text x="30" y="200" font-size="11">{{ series[0]?.date }}</text>
      <text x="770" y="200" text-anchor="end" font-size="11">
        {{ series.at(-1)?.date }}
      </text>
    </svg>
  </figure>
</template>
