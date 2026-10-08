<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{ items: { content: string; status: string }[] }>();
const completed = computed(() => props.items.filter((item) => item.status === "completed").length);
const labels: Record<string, string> = {
  pending: "待处理",
  in_progress: "进行中",
  completed: "已完成",
};
</script>

<template>
  <section class="todo-plan" aria-label="任务计划">
    <header class="todo-heading">
      <span>任务计划</span>
      <span class="todo-count">{{ completed }} / {{ items.length }} 已完成</span>
    </header>
    <div
      class="todo-progress"
      role="progressbar"
      aria-label="任务完成进度"
      :aria-valuenow="completed"
      :aria-valuemax="items.length"
      :aria-valuemin="0"
    >
      <span :style="{ width: `${items.length ? (completed / items.length) * 100 : 0}%` }" />
    </div>
    <ol class="tool-todos">
      <li v-for="(item, index) in items" :key="index" :class="item.status">
        <i
          :class="
            item.status === 'completed'
              ? 'ri-checkbox-circle-line'
              : item.status === 'in_progress'
                ? 'ri-loader-4-line'
                : 'ri-checkbox-blank-circle-line'
          "
          aria-hidden="true"
        />
        <span class="todo-content">{{ item.content }}</span>
        <span class="todo-status">{{ labels[item.status] }}</span>
      </li>
    </ol>
  </section>
</template>

<style scoped lang="scss">
.todo-plan {
  max-width: 760px;
  padding: 14px 16px 8px;
  border-radius: 12px;
  background: #f8f9fb;
  white-space: normal;
  line-height: 1.6;
}
.todo-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  font-weight: 600;
  color: #505866;
}
.todo-count {
  font-size: 12px;
  font-weight: 400;
  color: #9299a5;
}
.todo-progress {
  height: 3px;
  margin: 10px 0 8px;
  overflow: hidden;
  border-radius: 3px;
  background: #e9ecf1;
  span {
    display: block;
    height: 100%;
    background: var(--chat-run-color, #4074ed);
    transition: width 200ms;
  }
}
.tool-todos {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 300px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #dce0e7 transparent;
  li {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 9px 8px;
    margin: 2px 0;
    border-radius: 7px;
  }
  li:last-child {
    border-bottom: 0;
  }
  i {
    flex-shrink: 0;
    font-size: 17px;
    line-height: 22px;
    color: #a0a6af;
  }
  .todo-content {
    flex: 1;
    min-width: 0;
    color: #505866;
    font-size: 13px;
    line-height: 22px;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
  }
  .todo-status {
    flex-shrink: 0;
    font-size: 12px;
    color: #9299a5;
    line-height: 22px;
  }
  .in_progress {
    background: #edf2fc;
    i,
    .todo-status {
      color: var(--chat-run-color, #4074ed);
    }
  }
  .completed {
    .todo-content {
      color: #8a929e;
    }
    i,
    .todo-status {
      color: #429574;
    }
  }
}
</style>
