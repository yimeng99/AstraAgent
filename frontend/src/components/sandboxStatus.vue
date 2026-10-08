<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { requestApi, userHeaders } from "@/utils/request";

const props = defineProps<{ userId: string }>();
const status = ref<{
  state: string;
  available: boolean;
  busy: boolean;
  running_seconds: number | null;
} | null>(null);
const failed = ref(false);
const label = computed(() => {
  if (failed.value) return "状态获取失败";
  if (!status.value) return "查询中";
  if (status.value.busy) return "使用中";
  if (status.value.available) return "可用";
  return (
    (
      {
        PAUSED: "已暂停",
        NOT_CREATED: "未创建",
        DISABLED: "未启用",
        MISSING: "不存在",
        UNAVAILABLE: "不可用",
        RUNNING: "准备中",
        CREATING: "创建中",
      } as Record<string, string>
    )[status.value.state] ?? "暂不可用"
  );
});
const detail = computed(() => {
  const seconds = status.value?.running_seconds;
  return seconds == null
    ? `沙箱：${label.value}`
    : `沙箱：${label.value}，本次运行 ${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
});

watch(
  () => props.userId,
  (user, _, onCleanup) => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    status.value = null;
    failed.value = false;
    async function refresh() {
      try {
        const result = await requestApi<NonNullable<typeof status.value>>({
          url: "/sandbox/status",
          headers: userHeaders(user),
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          status.value = result;
          failed.value = false;
        }
      } catch {
        if (!controller.signal.aborted) {
          status.value = null;
          failed.value = true;
        }
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 10000);
      }
    }
    void refresh();
    onCleanup(() => {
      controller.abort();
      clearTimeout(timer);
    });
  },
  { immediate: true },
);
</script>

<template>
  <span
    class="sandbox-status"
    :class="{ available: status?.available && !failed }"
    :title="detail"
    role="status"
    >● {{ label }}</span
  >
</template>

<style scoped>
.sandbox-status {
  color: #909399;
  font-size: 12px;
  white-space: nowrap;
}
.sandbox-status.available {
  color: #32936f;
}
</style>
