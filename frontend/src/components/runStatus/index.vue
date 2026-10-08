<script setup lang="ts">
import {ref, computed, watch, onBeforeUnmount} from "vue";

const props = defineProps<{ active: boolean; label: string }>();
const elapsedSeconds = ref(0);
let runTimer: ReturnType<typeof setInterval> | undefined;

function clearRunTimer() {
  if (runTimer !== undefined) clearInterval(runTimer);
  runTimer = undefined;
}

watch(
    () => props.active,
    (active) => {
      clearRunTimer();
      elapsedSeconds.value = 0;
      if (active) {
        // 按真实经过时间计算，避免后台标签页定时器降频造成计时漂移。
        const started = Date.now();
        runTimer = setInterval(() => {
          elapsedSeconds.value = Math.floor((Date.now() - started) / 1000);
        }, 1000);
      }
    },
    {immediate: true},
);
onBeforeUnmount(clearRunTimer);
const elapsedLabel = computed(() =>
    elapsedSeconds.value < 60
        ? `${elapsedSeconds.value} 秒`
        : `${Math.floor(elapsedSeconds.value / 60)} 分 ${elapsedSeconds.value % 60} 秒`,
);
</script>

<template>
  <div v-if="active" class="run-status" role="status">
    <svg class="run-spinner" viewBox="0 0 24 24" aria-hidden="true">
      <circle class="run-spinner-track" cx="12" cy="12" r="9"/>
      <path class="run-spinner-arc" d="M12 3a9 9 0 0 1 9 9"/>
    </svg>
    <span aria-live="polite">{{ label }}</span>
    <span class="run-elapsed">用时 {{ elapsedLabel }}</span>
    <span class="run-dots" aria-hidden="true"><b></b><b></b><b></b></span>
  </div>
</template>

<style scoped lang="scss">
.run-status {
  display: flex;
  align-items: center;
  gap: 7px;
  min-height: 24px;
  margin: 8px 0 0;
  color: var(--chat-run-color);
  font-size: 12px;
  line-height: 20px;
  overflow-wrap: anywhere;
}

.run-spinner {
  display: block;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  fill: none;
  stroke: currentColor;
  stroke-width: 2.5;
  transform-origin: center;
  animation: run-spin 0.8s linear infinite;
}

.run-spinner-track {
  opacity: 0.12;
}

.run-spinner-arc {
  stroke-linecap: round;
}

.run-elapsed {
  color: inherit;
  white-space: nowrap;
}

.run-dots {
  display: inline-flex;
  align-items: center;
  height: 14px;
  gap: 4px;

  b {
    display: block;
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background: currentColor;
    animation: run-bounce 1.2s ease-in-out infinite;

    &:nth-child(2) {
      animation-delay: 0.15s;
    }

    &:nth-child(3) {
      animation-delay: 0.3s;
    }
  }
}

@keyframes run-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes run-bounce {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.35;
  }
  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}

@keyframes run-fade {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  // 降低旋转速度并取消圆点跳动，仍保留用户要求的运行指示。
  .run-spinner {
    animation-duration: 2.4s;
  }
  .run-dots b {
    animation-name: run-fade;
    animation-duration: 2s;
  }
}
</style>
