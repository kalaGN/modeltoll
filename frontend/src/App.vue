<script setup lang="ts">
import { onMounted } from "vue";
import { loadBranding } from "./composables/branding";
onMounted(loadBranding);
</script>
<template><RouterView /></template>
