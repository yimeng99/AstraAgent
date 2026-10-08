<script setup lang="ts">
import { computed } from "vue";
import type { ExecutionFailure } from "@/types/chat";
import { failureMessage, failureTime } from "@/utils/executionFailure";

const props = defineProps<{ failure: ExecutionFailure; historical: boolean }>();
const message = computed(() => failureMessage(props.failure));
const time = computed(() => failureTime(props.failure.occurred_at));
</script>

<template>
  <div
    :class="failure.reason === 'user_stop' ? 'execution-stopped' : 'execution-failure'"
    :role="historical || failure.reason === 'user_stop' ? 'status' : 'alert'"
  >
    <span class="execution-record">{{ historical ? "历史执行记录" : "本次执行" }} · </span>
    <time :datetime="failure.occurred_at">{{ time }}</time>
    <span> · </span>
    <span>{{ message }}</span>
  </div>
</template>

<style scoped>
.execution-stopped {
  margin: 2px 0 6px;
  color: #909399;
  font-size: 14px;
}
.execution-failure {
  margin: 6px 0;
  color: #c45656;
  font-size: 14px;
}
.execution-record,
time {
  color: #909399;
  font-size: 12px;
}
</style>
