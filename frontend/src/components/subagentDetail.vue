<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from "vue";
import { requestApi, userHeaders } from "@/utils/request";
import Markdown from "@/components/markdown.vue";

interface Detail {
  id: string;
  agent: string;
  description: string;
  status: string;
  truncated: boolean;
  messages: {
    id: string;
    kind: string;
    name: string;
    status: string;
    content: string;
    reasoning: string;
  }[];
}
const props = defineProps<{ callId: string | null; threadId: string | null; userId: string }>();
const emit = defineEmits<{ close: [] }>();
const detail = ref<Detail | null>(null);
const error = ref("");
const loading = ref(false);
let controller: AbortController | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
function stop() {
  controller?.abort();
  clearTimeout(timer);
}
function label(status: string) {
  return (
    (
      {
        running: "运行中",
        completed: "已完成",
        waiting: "等待确认",
        error: "失败",
        interrupted: "已中断",
      } as Record<string, string>
    )[status] ?? status
  );
}
async function load() {
  stop();
  if (!props.callId || !props.threadId) return;
  const ac = new AbortController();
  controller = ac;
  loading.value = !detail.value;
  try {
    const result = await requestApi<Detail | null>({
      url: `/threads/${encodeURIComponent(props.threadId)}/subagents/${encodeURIComponent(props.callId)}`,
      headers: userHeaders(props.userId),
      signal: ac.signal,
    });
    if (ac.signal.aborted) return;
    detail.value = result;
    error.value = "";
    if (!result || result.status === "running" || result.status === "waiting")
      timer = setTimeout(load, 2000);
  } catch {
    if (!ac.signal.aborted) error.value = "子任务详情加载失败，请重试。";
  } finally {
    if (!ac.signal.aborted) loading.value = false;
  }
}
watch(
  () => [props.callId, props.threadId, props.userId],
  () => {
    stop();
    detail.value = null;
    error.value = "";
    void load();
  },
  { immediate: true },
);
onBeforeUnmount(stop);
</script>

<template>
  <el-drawer
    :model-value="!!callId"
    title="子智能体运行详情"
    size="min(760px, 100vw)"
    @update:model-value="!$event && emit('close')"
  >
    <div v-if="error" role="alert">{{ error }} <el-button text @click="load">重试</el-button></div>
    <p v-if="loading && !detail">正在加载…</p>
    <p v-else-if="!detail && !error" class="muted">
      暂无运行记录。旧任务未采集的过程无法回放，新任务启动后会自动更新。
    </p>
    <section v-if="detail" class="subagent-detail">
      <div class="subagent-heading">
        <strong>{{ detail.agent }}</strong
        ><span>{{ label(detail.status) }}</span>
      </div>
      <details class="subagent-assignment">
        <summary>任务说明</summary>
        <p>{{ detail.description || "未记录任务说明" }}</p>
      </details>
      <article v-for="message in detail.messages" :key="message.id" class="subagent-message">
        <template v-if="message.kind === 'model'">
          <details v-if="message.reasoning">
            <summary>思考过程</summary>
            <Markdown :content="message.reasoning" />
          </details>
          <Markdown v-if="message.content" :content="message.content" />
        </template>
        <details v-else>
          <summary>调用工具 {{ message.name }} · {{ label(message.status) }}</summary>
          <pre>{{ message.content || "等待工具返回…" }}</pre>
        </details>
      </article>
      <p v-if="detail.status === 'running'" class="muted" role="status">
        子任务正在执行，详情自动更新…
      </p>
      <p v-if="detail.status === 'waiting'" class="muted">请在主会话中处理待确认事项。</p>
      <p v-if="detail.truncated" class="muted">运行记录较长，部分文本已截断。</p>
    </section>
  </el-drawer>
</template>

<style scoped>
.subagent-detail {
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.subagent-heading {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.subagent-heading span,
summary,
.muted {
  color: #8a94a6;
  font-size: 13px;
}
.subagent-assignment {
  margin: 18px 0;
}
.subagent-assignment p,
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.subagent-message {
  margin: 20px 0;
}
summary {
  cursor: pointer;
}
pre {
  max-height: 360px;
  overflow: auto;
  padding: 12px;
  background: #f7f8fa;
}
</style>
