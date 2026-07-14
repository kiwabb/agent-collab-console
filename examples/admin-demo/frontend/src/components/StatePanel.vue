<script setup lang="ts">
import { AlertCircle, LoaderCircle, RotateCcw } from "lucide-vue-next";

defineProps<{
  loading: boolean;
  error: string;
}>();

defineEmits<{ retry: [] }>();
</script>

<template>
  <div v-if="loading" class="state-panel" aria-live="polite">
    <LoaderCircle class="spin" :size="24" />
    <span>正在加载数据...</span>
  </div>
  <div v-else-if="error" class="state-panel state-panel--error" role="alert">
    <AlertCircle :size="24" />
    <div><strong>数据加载失败</strong><span>{{ error }}</span></div>
    <button class="secondary-button" @click="$emit('retry')"><RotateCcw :size="16" />重试</button>
  </div>
  <slot v-else />
</template>
