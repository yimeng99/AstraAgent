<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from "vue";
import { requestApi, userHeaders } from "@/utils/request";
import type { SessionMetrics } from "@/types/chat";

const props = defineProps<{
  threadId: string | null;
  userId: string;
  rounds: number;
  live: SessionMetrics | null;
}>();
const value = ref<SessionMetrics | null>(null);
const failed = ref(false);
let controller: AbortController | undefined;
let revision = 0;
watch(
  () => props.live,
  (live) => {
    if (live) {
      revision++;
      value.value = live;
      failed.value = false;
    }
  },
);
async function refresh() {
  controller?.abort();
  const thread = props.threadId;
  if (!thread) return;
  const ac = new AbortController();
  controller = ac;
  const started = revision;
  try {
    const result = await requestApi<SessionMetrics>({
      url: `/threads/${encodeURIComponent(thread)}/metrics`,
      headers: userHeaders(props.userId),
      signal: ac.signal,
    });
    if (!ac.signal.aborted && started === revision) {
      value.value = result;
      failed.value = false;
    }
  } catch {
    if (!ac.signal.aborted && started === revision) failed.value = true;
  }
}
watch(
  () => [props.threadId, props.userId],
  () => {
    revision++;
    value.value = null;
    failed.value = false;
    void refresh();
  },
  { immediate: true },
);
onBeforeUnmount(() => controller?.abort());
function duration(seconds?: number) {
  if (seconds === undefined) return "—";
  return seconds >= 60
    ? `${Math.floor(seconds / 60)}分 ${Math.floor(seconds % 60)}秒`
    : `${seconds.toFixed(1)}秒`;
}
function tokens(count: number | null | undefined) {
  if (count == null) return "—";
  return Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(count);
}
</script>

<template>
  <div v-if="threadId" class="session-metrics">
    <el-popover trigger="click" placement="top-start" :width="320">
      <template #reference>
        <button type="button" class="metrics-trigger" aria-label="查看会话统计">
          <i class="ri-dashboard-3-line" aria-hidden="true" />
          {{ rounds }} 轮 · {{ value?.steps ?? "—" }} 步 · {{ value?.tps?.toFixed(1) ?? "—" }} tok/s
        </button>
      </template>
      <section class="metrics-detail">
        <strong>会话统计</strong>
        <p v-if="failed">统计暂不可用 <button type="button" @click="refresh">重试</button></p>
        <dl>
          <dt>模型调用</dt>
          <dd>{{ value?.model_calls ?? "—" }} 次</dd>
          <dt>工具调用</dt>
          <dd>{{ value?.tool_calls ?? "—" }} 次</dd>
          <dt>模型用时</dt>
          <dd>{{ duration(value?.model_seconds) }}</dd>
          <dt>工具调用用时</dt>
          <dd>{{ duration(value?.tool_seconds) }}</dd>
          <dt>首 Token 平均（TTFT）</dt>
          <dd>{{ value?.ttft == null ? "—" : duration(value.ttft) }}</dd>
          <dt>输出速度（TPS）</dt>
          <dd>{{ value?.tps?.toFixed(1) ?? "—" }} tok/s</dd>
          <dt>输入 / 输出 Token</dt>
          <dd>
            {{ tokens(value?.usage_calls ? value.input_tokens : null) }} /
            {{ tokens(value?.usage_calls ? value.output_tokens : null) }}
          </dd>
          <dt>缓存命中</dt>
          <dd>
            {{
              value?.cache_hit_rate == null ? "—" : `${(value.cache_hit_rate * 100).toFixed(1)}%`
            }}
          </dd>
          <dt>上下文占用</dt>
          <dd>—</dd>
        </dl>
        <small
          >仅统计功能启用后的执行。主、子智能体合计；并行耗时累加。步数为观测到的图步骤，重试和恢复另计。未返回的用量不估算。</small
        >
        <small v-if="value && value.usage_calls < value.model_calls"
          >Token 用量仅覆盖 {{ value.usage_calls }}/{{ value.model_calls }} 次调用。</small
        >
      </section>
    </el-popover>
    <span
      ><i class="ri-database-2-line" aria-hidden="true" />
      {{ tokens(value?.total_tokens) }} tok</span
    >
    <span v-if="value?.cache_hit_rate != null"
      >缓存命中 {{ (value.cache_hit_rate * 100).toFixed(0) }}%</span
    >
  </div>
</template>

<style scoped>
.session-metrics {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 14px;
  margin: 8px 0;
  color: #8a909b;
  font-size: 12px;
}
.metrics-trigger {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 0;
  border-radius: 14px;
  padding: 4px 10px;
  background: transparent;
  box-shadow: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.metrics-trigger:hover {
  background: #eceef1;
  color: #475569;
}
.metrics-trigger:focus-visible {
  outline: 2px solid #90b6ff;
}
.metrics-detail {
  color: #737b87;
  font-size: 13px;
}
.metrics-detail strong {
  display: block;
  padding-bottom: 12px;
  color: #303843;
  border-bottom: 1px solid #eceef1;
}
.metrics-detail dl {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
}
.metrics-detail dd {
  margin: 0;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.metrics-detail small {
  display: block;
  line-height: 1.6;
  color: #9299a5;
}
</style>
