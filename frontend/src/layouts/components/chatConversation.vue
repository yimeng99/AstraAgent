<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from "vue";
import { storeToRefs } from "pinia";
import { ElMessage, ElMessageBox } from "element-plus";
import { useChatStore } from "@/stores/chat";
import { useUserStore } from "@/stores/user";
import { useAppStore } from "@/stores/app";
import { formatSize } from "@/utils/files";
import { openSandboxLink } from "@/utils/sandboxLinks";
import type { PreviewTarget } from "@/types/files";
import { File } from "@/components/icons";
import RunStatus from "@/components/runStatus/index.vue";
import SessionMetrics from "@/components/sessionMetrics.vue";
import SubagentDetail from "@/components/subagentDetail.vue";
import ChatWelcome from "@/components/chatWelcome.vue";
import UserMessage from "@/components/userMessage.vue";
import ConversationOutline from "@/components/conversationOutline.vue";
import ChatComposer from "@/components/chatComposer.vue";
import ReasoningBlock from "@/components/reasoningBlock.vue";
import ToolCallBlock from "@/components/toolCallBlock.vue";
import ExecutionFailure from "@/components/executionFailure.vue";
import Markdown from "@/components/markdown.vue";
import Approvals from "@/components/approvals.vue";
import UserQuestions from "@/components/userQuestions.vue";
import FilePreview from "@/components/filePreview.vue";
import SandboxFiles from "@/components/sandboxFiles.vue";
import SandboxStatus from "@/components/sandboxStatus.vue";

const chat = useChatStore();
const { agentTeamLabel } = storeToRefs(useAppStore());
const { userId } = storeToRefs(useUserStore());
const {
  threadId,
  metrics,
  title,
  messages,
  approvals,
  questions,
  busy,
  sending,
  switching,
  recovering,
  recoveryError,
  interruptedRun,
  error,
  hasPendingInteraction,
  questionSubmitting,
  draft,
  items,
  uploadErrors,
  canSend,
  externalBusy,
  researchProgress,
  typingId,
} = storeToRefs(chat);
const scroller = ref<HTMLElement>();
async function resumeInterrupted() {
  const needsConfirmation = interruptedRun.value?.requires_tool_confirmation ?? false;
  if (needsConfirmation) {
    try {
      await ElMessageBox.confirm(
        "中断前的工具可能已生成文件或完成写入。请先核对会话文件；继续会重新执行尚未确认结果的工具，可能重复生成或覆盖文件。",
        "确认恢复任务",
        { confirmButtonText: "已核对，允许重试", cancelButtonText: "暂不恢复", type: "warning" },
      );
    } catch { return; }
  }
  await chat.resumeInterrupted(needsConfirmation);
}
const messageColumn = ref<HTMLElement>();
const preview = ref<PreviewTarget | null>(null);
const filesOpen = ref(false);
const interactionOpen = ref(false);
const selectedSubagent = ref<string | null>(null);
const running = computed(() => busy.value && !hasPendingInteraction.value);
const runningSubagentCount = computed(() => {
  if (!busy.value || switching.value) return 0;
  const calls = new Set<string>();
  for (const message of messages.value) {
    for (const tool of message.tools ?? []) {
      if (tool.name === "task" && tool.status === "running") calls.add(tool.id);
    }
  }
  return calls.size;
});
const runLabel = computed(() => {
  const latest = messages.value.find((message) => message.id === typingId.value);
  if (
    externalBusy.value ||
    messages.value.some((message) => message.tools?.some((tool) => tool.status === "running"))
  )
    return "正在调用工具";
  if (researchProgress.value) return researchProgress.value;
  return latest?.content.trim() ? "正在生成" : "正在思考";
});
watch(
  [() => approvals.value.map((item) => item.id).join("|"), () => questions.value.length],
  ([ids, count]) => {
    interactionOpen.value = !!ids && !count;
  },
);
watch(threadId, () => {
  selectedSubagent.value = null;
  preview.value = null;
  interactionOpen.value = false;
});
watch(preview, (_, previous) => {
  if (previous?.url.startsWith("blob:")) URL.revokeObjectURL(previous.url);
});
onBeforeUnmount(() => {
  if (preview.value?.url.startsWith("blob:")) URL.revokeObjectURL(preview.value.url);
});
async function openChatFile(url: string) {
  const selected = threadId.value;
  if (!selected) return;
  try {
    const target = await openSandboxLink(url, selected, userId.value);
    if (selected !== threadId.value) {
      if (target) URL.revokeObjectURL(target.url);
      return;
    }
    if (target) preview.value = target;
  } catch (issue) {
    ElMessage.error((issue as Error).message);
  }
}
let following = true;
const showScrollToBottom = ref(false);
let scrollFrame = 0;
let lastScrollTop = 0;
let resizeObserver: ResizeObserver | undefined;

function onConversationScroll() {
  const element = scroller.value;
  if (!element) return;
  const nearBottom = element.scrollHeight - element.clientHeight - element.scrollTop <= 4;
  following = nearBottom && element.scrollTop >= lastScrollTop;
  showScrollToBottom.value = !nearBottom;
  lastScrollTop = element.scrollTop;
}

function pauseFollowing(event: WheelEvent) {
  if (event.deltaY < 0) following = false;
}

function scrollToBottom() {
  following = true;
  scheduleScroll();
}

function scheduleScroll() {
  if (scrollFrame) return;
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = 0;
    const element = scroller.value;
    if (!element) return;
    if (following) element.scrollTop = element.scrollHeight;
    showScrollToBottom.value = element.scrollHeight - element.clientHeight - element.scrollTop > 4;
    lastScrollTop = element.scrollTop;
  });
}

// 只观察实际布局变化，避免每个流式 token 深度遍历整个历史；读历史时不抢滚动位置。
onMounted(() => {
  resizeObserver = new ResizeObserver(scheduleScroll);
  if (messageColumn.value) resizeObserver.observe(messageColumn.value);
  if (scroller.value) resizeObserver.observe(scroller.value);
  scheduleScroll();
});
watch(
  [threadId, switching],
  () => {
    following = true;
    showScrollToBottom.value = false;
    lastScrollTop = 0;
    scheduleScroll();
  },
  { flush: "post" },
);
onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  cancelAnimationFrame(scrollFrame);
});
</script>

<template>
  <div class="chat-content">
    <main class="main">
      <header class="chat-header">
        <div class="chat-heading">
          <h1 :title="title">{{ title }}</h1>
          <span class="agent-team-label" title="主智能体按任务需要调度子智能体协作">
            <i class="remix-icon ri-group-line" aria-hidden="true" />
            <span>{{ agentTeamLabel }}</span>
            <strong
              class="agent-running-count"
              :class="{ active: runningSubagentCount > 0 }"
              role="status"
              aria-live="polite"
            >{{ runningSubagentCount }} 个执行中</strong>
          </span>
        </div>
        <button
          class="files-toggle"
          :class="{ active: filesOpen }"
          type="button"
          :aria-expanded="filesOpen"
          @click="filesOpen = !filesOpen"
        >
          <el-icon><File /></el-icon><span>文件</span>
          <SandboxStatus :user-id="userId" />
        </button>
      </header>
      <div class="conversation-area">
        <section
          ref="scroller"
          v-loading="switching"
          element-loading-text="正在加载会话…"
          class="conversation"
          @scroll.passive="onConversationScroll"
          @wheel.passive="pauseFollowing"
        >
          <div ref="messageColumn" class="message-column">
            <p v-if="busy && researchProgress" class="muted" role="status" aria-live="polite">
              {{ researchProgress }}
            </p>
            <ChatWelcome v-if="!messages.length" />
            <template v-for="message in messages" :key="message.id">
              <UserMessage
                v-if="message.role === 'user'"
                :message="message"
                :data-turn-id="message.id"
                @preview="preview = $event"
                @file-link="openChatFile"
              />
              <article v-else class="message" :class="message.role">
                <ReasoningBlock
                  v-if="message.reasoning"
                  :content="message.reasoning"
                  :active="busy && message.id === typingId"
                  :thinking="busy && message.id === typingId && !message.content.trim()"
                />
                <div v-if="message.tools?.length" class="tool-events" aria-label="工具调用">
                  <ToolCallBlock
                    v-for="(tool, index) in message.tools"
                    :key="tool.id || index"
                    :tool="tool"
                    @subagent="selectedSubagent = $event"
                    :waiting="!busy && hasPendingInteraction && tool.name === 'task'"
                  />
                </div>
                <Markdown
                  v-if="message.content.trim()"
                  :content="message.content"
                  :streaming="busy && message.id === typingId && message.role === 'assistant'"
                  @file-link="openChatFile"
                />
                <span
                  v-else-if="
                    busy &&
                    message.role === 'assistant' &&
                    message.id === typingId &&
                    !message.reasoning
                  "
                  class="muted"
                  >{{ externalBusy ? "正在调用工具…" : "正在处理…" }}</span
                >
                <div class="file-list">
                  <button
                    v-for="file in message.attachments"
                    :key="file.fileId"
                    class="file-card"
                    @click="
                      preview = {
                        fileId: file.fileId,
                        filename: file.filename,
                        url: file.previewUrl,
                        size: file.size,
                      }
                    "
                  >
                    <img
                      v-if="file.kind === 'image'"
                      :src="file.previewUrl"
                      :alt="file.filename"
                    /><el-icon v-else><File /></el-icon
                    ><span
                      >{{ file.filename }}<small>{{ formatSize(file.size) }}</small></span
                    >
                  </button>
                </div>
                <ExecutionFailure
                  v-if="message.failure"
                  :failure="message.failure"
                  :historical="!busy || message.id !== typingId"
                />
              </article>
            </template>
            <RunStatus :key="threadId ?? 'new'" :active="running" :label="runLabel" />
          </div>
        </section>
        <ConversationOutline
          v-if="!switching"
          :messages="messages"
          :scroller="scroller"
          @navigate="following = false"
        />
        <button
          v-if="showScrollToBottom && !switching"
          class="scroll-to-bottom"
          type="button"
          aria-label="回到底部"
          title="回到底部"
          @click="scrollToBottom"
        >
          <i class="ri-arrow-down-s-line" aria-hidden="true" />
        </button>
      </div>
      <div class="input-area">
        <div v-if="interruptedRun && !busy" class="pending-interaction-bar" role="status">
          <span>任务执行中断，可从保存的位置继续</span>
          <el-button text type="primary" @click="resumeInterrupted">恢复任务</el-button>
        </div>
        <p v-if="recovering" class="muted" role="status">正在恢复待处理事项…</p>
        <div v-if="recoveryError" role="alert">
          <span class="error">{{ recoveryError }}</span>
          <el-button text type="primary" :loading="recovering" @click="chat.recover()"
            >重试</el-button
          >
        </div>
        <div v-if="approvals.length && !questions.length" class="pending-interaction-bar">
          <i class="ri-pause-circle-line" aria-hidden="true" />
          <span>任务等待你确认操作</span>
          <el-button text type="primary" @click="interactionOpen = true">查看并确认</el-button>
        </div>
        <el-alert
          v-if="error && !messages.some((m) => m.failure?.message === error)"
          :title="error"
          type="error"
          show-icon
          :closable="false"
        />
        <UserQuestions
          v-show="questions.length || questionSubmitting"
          :items="questions"
          :busy="busy || questionSubmitting || switching"
          :thread-id="threadId"
          :user-id="userId"
          @submit="chat.submitQuestions"
        />
        <ChatComposer
          v-if="!questions.length && !questionSubmitting"
          v-model="draft"
          :items="items"
          :busy="busy"
          :sending="sending"
          :disabled="switching || recovering || !!recoveryError || hasPendingInteraction"
          :placeholder="hasPendingInteraction ? '请先确认待执行操作' : undefined"
          :can-send="canSend"
          @send="chat.send"
          @stop="chat.stop"
          @files="chat.addFiles"
          @retry="chat.retry"
          @remove="chat.remove"
        />
        <p v-for="issue in uploadErrors" :key="issue" class="error">{{ issue }}</p>
        <SessionMetrics :thread-id="threadId" :user-id="userId" :live="metrics" :rounds="messages.filter(message => message.role === 'user').length" />
      </div>
    </main>

    <SandboxFiles
      v-if="filesOpen"
      :thread-id="threadId"
      :user-id="userId"
      :busy="busy || switching || sending"
      @close="filesOpen = false"
      @preview="preview = $event"
    />
    <el-dialog
      v-model="interactionOpen"
      title="确认操作"
      width="min(560px, calc(100vw - 32px))"
      class="interaction-dialog"
      :close-on-click-modal="false"
      :close-on-press-escape="!busy"
      :show-close="!busy"
    >
      <p class="interaction-dialog-intro">请核对下面的操作，确认后继续原任务。</p>
      <p v-if="error" role="alert" style="color: #c45656">{{ error }}</p>
      <div class="interaction-dialog-body">
        <Approvals :items="approvals" :busy="busy" @resume="chat.resume" />
      </div>
      <p class="interaction-dialog-note">进度已保存，关闭窗口后也可以稍后处理。</p>
    </el-dialog>
    <SubagentDetail :call-id="selectedSubagent" :thread-id="threadId" :user-id="userId" @close="selectedSubagent = null" />
    <FilePreview :target="preview" @close="preview = null" />
  </div>
</template>
<style scoped lang="scss">
.agent-running-count {
  padding: 2px 8px;
  border-radius: 6px;
  background: #f3f4f6;
  color: #9299a5;
  font-size: 12px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  &.active {
    background: #edf2fc;
    color: var(--chat-run-color, #4074ed);
  }
}
.files-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding: 8px 12px;
  border: 1px solid #e7eaf0;
  border-radius: 10px;
  background: #fff;
  color: #43536d;
  cursor: pointer;
  &:hover,
  &.active {
    background: #f5f7fa;
  }
  &:focus-visible {
    outline: 2px solid #7894b9;
    outline-offset: 2px;
  }
}
.conversation-area {
  position: relative;
  display: flex;
  flex: 1;
  min-height: 0;
}
.scroll-to-bottom {
  position: absolute;
  right: max(24px, calc((100% - 932px) / 2));
  bottom: 16px;
  z-index: 2;
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  padding: 0;
  border: 1px solid #e5e7eb;
  border-radius: 50%;
  background: #fff;
  color: #30343b;
  box-shadow: 0 3px 12px rgb(24 39 64 / 8%);
  cursor: pointer;
  font-size: 20px;
  transition:
    background 150ms,
    box-shadow 150ms;
  &:hover {
    background: #f5f7fa;
    box-shadow: 0 4px 14px rgb(24 39 64 / 12%);
  }
  &:focus-visible {
    outline: 2px solid var(--chat-run-color);
    outline-offset: 3px;
  }
}

.chat-content {
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
</style>
