<script setup lang="ts">
defineProps<{ title: string; subtitle: string }>();
</script>
<template>
  <header class="page-heading">
    <div>
      <p class="eyebrow">MODELTOLL / CONSOLE</p>
      <h1 class="page-title">{{ title }}</h1>
      <p class="muted">{{ subtitle }}</p>
    </div>
    <div class="heading-actions"><slot /></div>
  </header>
</template>
