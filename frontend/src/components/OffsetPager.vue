<script setup lang="ts">
defineProps<{
  name: string;
  page: number;
  total: number;
  more: boolean;
  busy: boolean;
  ready: boolean;
}>();
defineEmits<{ change: [delta: number] }>();
</script>
<template>
  <div class="pagination">
    <span :id="`${name}-page-label`">{{
      ready ? `第 ${page} 页 · 共 ${total} 条 · 每页 20 条` : "暂无分页数据"
    }}</span>
    <div>
      <button
        :id="`${name}-prev`"
        class="button-secondary"
        :disabled="busy || !ready || page <= 1"
        @click="$emit('change', -1)"
      >
        上一页</button
      ><button
        :id="`${name}-next`"
        class="button-secondary"
        :disabled="busy || !ready || !more || page >= 10000"
        @click="$emit('change', 1)"
      >
        下一页
      </button>
    </div>
  </div>
</template>
