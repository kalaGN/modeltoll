<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from "vue";
defineProps<{ title: string; id: string; busy?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const dialog = ref<HTMLDialogElement>();
let previous: HTMLElement | null = null;
onMounted(() => {
  previous = document.activeElement as HTMLElement;
  dialog.value?.showModal();
});
onBeforeUnmount(() => {
  dialog.value?.close();
  if (previous?.isConnected) previous.focus();
});
</script>
<template>
  <dialog
    :id="id"
    ref="dialog"
    :aria-labelledby="id + '-title'"
    class="app-modal"
    @cancel.prevent="!busy && emit('close')"
  >
    <header>
      <h2 :id="id + '-title'">{{ title }}</h2>
      <button
        type="button"
        aria-label="关闭弹窗"
        :disabled="busy"
        @click="emit('close')"
      >
        ×
      </button>
    </header>
    <slot />
  </dialog>
</template>
