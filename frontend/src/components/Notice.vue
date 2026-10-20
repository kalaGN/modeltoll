<script setup lang="ts">
defineProps<{ message?: string; success?: boolean }>();
</script>
<template>
  <p
    v-if="message"
    :role="success ? 'status' : 'alert'"
    :class="['notice', { 'notice-success': success }]"
  >
    {{ message }}
  </p>
</template>
