<script setup lang="ts">
defineProps<{ items: { label: string; value: string; id?: string }[] }>();
</script>
<template>
  <section
    class="metric-grid"
    :style="{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }"
  >
    <div v-for="item in items" :key="item.label" class="metric">
      <p class="muted">{{ item.label }}</p>
      <p :id="item.id" class="metric-value">{{ item.value }}</p>
    </div>
  </section>
</template>
