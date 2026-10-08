<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { ChatMessage } from "@/types/chat";

const props = defineProps<{ messages: ChatMessage[]; scroller?: HTMLElement }>();
const emit = defineEmits<{ navigate: [] }>();
const turns = computed(() => props.messages.filter((message) => message.role === "user"));
const active = ref(0);
let frame = 0;

function updateActive() {
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    const container = props.scroller;
    if (!container) return;
    const top = container.getBoundingClientRect().top + 48;
    let current = 0;
    container.querySelectorAll<HTMLElement>("[data-turn-id]").forEach((element, index) => {
      if (element.getBoundingClientRect().top <= top) current = index;
    });
    active.value = current;
  });
}

function jumpTo(id: string) {
  const container = props.scroller;
  const target = Array.from(container?.querySelectorAll<HTMLElement>("[data-turn-id]") ?? []).find(
    (element) => element.dataset.turnId === id,
  );
  if (!container || !target) return;
  emit("navigate");
  // 只移动对话滚动容器，避免 scrollIntoView 连带滚动整个页面。
  container.scrollTop +=
    target.getBoundingClientRect().top - container.getBoundingClientRect().top - 24;
  updateActive();
}

watch(
  () => [props.scroller, turns.value.map((turn) => turn.id).join("|")] as const,
  (_, __, onCleanup) => {
    const container = props.scroller;
    if (!container) return;
    container.addEventListener("scroll", updateActive, { passive: true });
    const observer = new ResizeObserver(updateActive);
    if (container.firstElementChild) observer.observe(container.firstElementChild);
    updateActive();
    onCleanup(() => {
      container.removeEventListener("scroll", updateActive);
      observer.disconnect();
    });
  },
  { flush: "post", immediate: true },
);
onBeforeUnmount(() => cancelAnimationFrame(frame));
</script>

<template>
  <nav v-if="turns.length" class="conversation-outline" aria-label="对话轮次定位">
    <el-tooltip
      v-for="(turn, index) in turns"
      :key="turn.id"
      placement="left"
      effect="light"
      :popper-style="{ borderRadius: '16px', boxShadow: '0 4px 20px rgb(24 39 64 / 8%)' }"
      :show-after="120"
      :offset="14"
      :show-arrow="false"
    >
      <template #content>
        <div class="turn-preview">
          <strong>第 {{ index + 1 }} 轮</strong>
          <p>
            {{
              turn.content ||
              turn.attachments?.map((file) => file.filename).join("、") ||
              "附件消息"
            }}
          </p>
        </div>
      </template>
      <button
        type="button"
        class="turn-marker"
        :class="{ active: active === index }"
        :aria-label="`跳转到第 ${index + 1} 轮`"
        :aria-current="active === index ? 'step' : undefined"
        @click="jumpTo(turn.id)"
      >
        <span />
      </button>
    </el-tooltip>
  </nav>
</template>

<style scoped lang="scss">
.conversation-outline {
  position: absolute;
  z-index: 3;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  max-height: 60%;
  overflow-y: auto;
  scrollbar-width: none;
  padding: 4px;
  border-radius: 12px;
  background: rgb(255 255 255 / 90%);
  &::-webkit-scrollbar {
    display: none;
  }
}
.turn-marker {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 28px;
  height: 14px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  span {
    width: 12px;
    height: 2px;
    border-radius: 2px;
    background: #d7d9dd;
    transition:
      width 150ms,
      background 150ms;
  }
  &.active span,
  &:hover span,
  &:focus-visible span {
    width: 22px;
    background: #626975;
  }
  &:focus-visible {
    outline: 2px solid var(--chat-run-color);
    border-radius: 4px;
  }
}
.turn-preview {
  width: min(320px, calc(100vw - 100px));
  padding: 6px 8px;
  font-size: 14px;
  line-height: 1.6;
  strong {
    color: #30343b;
    font-weight: 500;
  }
  p {
    margin: 4px 0 0;
    color: #9299a5;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    overflow-wrap: anywhere;
  }
}
</style>
