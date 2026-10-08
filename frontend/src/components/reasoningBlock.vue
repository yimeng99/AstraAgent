<script setup lang="ts">
import { ref, watch } from "vue";
import { useStreamingText } from "@/composables/useStreamingText";
import { chatConfig } from "@/config";

const props = defineProps<{ content: string; active: boolean; thinking: boolean }>();
const expanded = ref(false);
const displayed = useStreamingText(
  () => props.content,
  () => props.thinking && expanded.value,
);
// 只在阶段开始、结束时同步，流式增量不会覆盖用户的手动展开状态。
watch(
  () => props.active,
  (active) => (expanded.value = active && chatConfig.autoExpandReasoning),
  { immediate: true },
);
</script>

<template>
  <div class="reasoning">
    <button
      type="button"
      class="reasoning-toggle"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <i class="ri-brain-line" aria-hidden="true" />
      <span>{{ thinking ? "正在思考" : "思考过程" }}</span>
      <svg
        class="reasoning-chevron"
        :class="{ expanded }"
        width="16"
        height="16"
        viewBox="0 0 16 16"
        aria-hidden="true"
      >
        <path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5" />
      </svg>
    </button>
    <div class="reasoning-panel" :class="{ expanded }" :aria-hidden="!expanded">
      <div class="reasoning-panel-inner">
        <div class="reasoning-content">
          {{ displayed
          }}<span v-if="thinking && expanded" class="streaming-cursor" aria-hidden="true" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.reasoning-panel {
  display: grid;
  grid-template-rows: 0fr;
  opacity: 0;
  visibility: hidden;
  transition:
    grid-template-rows 220ms ease,
    opacity 180ms ease,
    visibility 0s 220ms;

  &.expanded {
    grid-template-rows: 1fr;
    opacity: 1;
    visibility: visible;
    transition-delay: 0s;
  }
}
.reasoning-panel-inner {
  min-height: 0;
  overflow: hidden;
}
@media (prefers-reduced-motion: reduce) {
  .reasoning-panel {
    transition: none;
  }
}
</style>
