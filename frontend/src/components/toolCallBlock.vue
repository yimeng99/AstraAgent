<script setup lang="ts">
import { computed, ref } from "vue";
import ToolTodoList from "./toolTodoList.vue";
import { parseToolTodos } from "@/utils/toolTodos";
import type { ChatMessage } from "@/types/chat";

const props = defineProps<{ tool: NonNullable<ChatMessage["tools"]>[number]; waiting?: boolean }>();
const todos = computed(() =>
  props.tool.name === "write_todos" ? parseToolTodos(props.tool.result || "") : [],
);
const expanded = ref(false);
const emit = defineEmits<{ subagent: [id: string] }>();
</script>

<template>
  <div class="reasoning tool-call">
    <button
      type="button"
      class="reasoning-toggle"
      :aria-expanded="expanded"
      @click="tool.name === 'task' ? emit('subagent', tool.id) : (expanded = !expanded)"
    >
      <i class="ri-tools-line" aria-hidden="true" />
      <span>{{ tool.name === "task" ? "派发子智能体" : `调用工具 ${tool.name}` }}</span>
      <span class="tool-status" :class="tool.status">
        {{
          tool.status === "running"
            ? waiting
              ? "等待确认"
              : "调用中"
            : tool.status === "error"
              ? "失败"
              : tool.status === "interrupted"
                ? "已中断"
                : "已完成"
        }}
      </span>
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
    <div
      v-if="tool.name !== 'task'"
      class="tool-panel"
      :class="{ expanded }"
      :aria-hidden="!expanded"
    >
      <div class="tool-panel-inner">
        <div
          class="reasoning-content tool-result"
          :class="{ 'has-todos': todos.length && tool.status !== 'running' }"
        >
          <ToolTodoList v-if="todos.length && tool.status !== 'running'" :items="todos" />
          <template v-else>{{
            tool.status === "running"
              ? waiting
                ? "请处理会话中的待确认事项后继续。"
                : "正在等待工具返回…"
              : tool.result || "工具未返回文本。"
          }}</template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.tool-panel {
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
.tool-panel-inner {
  min-height: 0;
  overflow: hidden;
}
.tool-result {
  max-height: 320px;
  overflow: auto;
  &.has-todos {
    max-height: none;
    overflow: visible;
    border-left: 0;
    padding: 0;
    margin: 10px 0 6px 26px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .tool-panel {
    transition: none;
  }
}
</style>
