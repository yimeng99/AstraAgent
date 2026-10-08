import { ref, computed, onScopeDispose } from "vue";
import { defineStore } from "pinia";
import { useUserStore } from "./user";
import { chatApi, followChat, streamChat, type RunState } from "@/api/chat";
import { useAttachmentQueue } from "@/composables/useAttachmentQueue";
import { toChatMessages } from "@/utils/history";
import { loadActiveThread, saveActiveThread } from "@/utils/storage";
import type {
  ThreadSummary,
  ChatMessage,
  ApprovalInfo,
  QuestionInfo,
  ResumeRequest,
  StreamStatus,
  ExecutionFailure,
} from "@/types/chat";
import type { Attachment } from "@/types/files";

// 会话列表、当前消息与待处理事项只在这里持有；浏览器存储只记住选中的 ID。
export const useChatStore = defineStore("chat", () => {
  const user = useUserStore();
  const threadId = ref<string | null>(null);
  const threads = ref<ThreadSummary[]>([]);
  const messages = ref<ChatMessage[]>([]);
  const metrics = ref<import("@/types/chat").SessionMetrics | null>(null);
  const approvals = ref<ApprovalInfo[]>([]);
  const questions = ref<QuestionInfo[]>([]);
  const status = ref<StreamStatus>("idle");
  const error = ref<string | null>(null);
  const threadsError = ref<string | null>(null);
  const recoveryError = ref<string | null>(null);
  const interruptedRun = ref<RunState | null>(null);
  const backgroundRunning = ref(false);

  async function resumeInterrupted(retryTools = false) {
    const run = interruptedRun.value;
    if (!run || busy.value) return;
    interruptedRun.value = null;
    await runStream("", [], undefined, false, {
      checkpoint_id: run.checkpoint_id,
      retry_tools: retryTools,
    });
  }
  const loading = ref(false),
    switching = ref(false),
    recovering = ref(false);
  const sending = ref(false),
    questionSubmitting = ref(false),
    managingThread = ref(false);
  const draft = ref("");
  const externalBusy = ref(false),
    researchProgress = ref(""),
    typingId = ref("");
  const uploads = useAttachmentQueue(() => user.userId);
  const busy = computed(() => status.value === "submitting" || status.value === "streaming");
  const title = computed(
    () => threads.value.find((item) => item.id === threadId.value)?.title || "新会话",
  );
  const hasPendingInteraction = computed(
    () => !!(approvals.value.length || questions.value.length),
  );
  const navigationDisabled = computed(
    () => switching.value || questionSubmitting.value || managingThread.value,
  );
  const canSend = computed(
    () =>
      !busy.value &&
      !backgroundRunning.value &&
      !navigationDisabled.value &&
      !recovering.value &&
      !recoveryError.value &&
      !hasPendingInteraction.value &&
      !uploads.uploading.value &&
      !uploads.items.value.some((item) => item.status === "error") &&
      (!!draft.value.trim() || !!uploads.attachments.value.length),
  );
  let selection = 0;
  let listVersion = 0;
  let initialized = false;
  let streamController: AbortController | null = null;
  let historyController: AbortController | null = null;
  let recoveryController: AbortController | null = null;

  async function refresh() {
    const version = ++listVersion;
    loading.value = true;
    try {
      const result = await chatApi.list(user.userId);
      if (version === listVersion) {
        threads.value = result;
        threadsError.value = null;
      }
    } catch (issue) {
      if (version === listVersion) threadsError.value = (issue as Error).message;
    } finally {
      if (version === listVersion) loading.value = false;
    }
  }

  async function recover(): Promise<RunState | null> {
    interruptedRun.value = null;
    recoveryController?.abort();
    const tid = threadId.value;
    recoveryError.value = null;
    if (!tid) {
      recovering.value = false;
      return null;
    }
    const ac = new AbortController();
    recoveryController = ac;
    recovering.value = true;
    try {
      const result = await chatApi.interactions(user.userId, tid, ac.signal);
      const run = await chatApi.streamStatus(user.userId, tid, ac.signal);
      if (ac.signal.aborted || tid !== threadId.value) return null;
      interruptedRun.value = run.recoverable ? run : null;
      backgroundRunning.value = run.active || run.state === "running";
      approvals.value = result.approvals.filter((item) => item.status === "pending");
      questions.value = result.questions.filter((item) => item.status === "pending");
      return run;
    } catch {
      if (!ac.signal.aborted && tid === threadId.value)
        recoveryError.value = "待处理事项加载失败，请重试后继续。";
      return null;
    } finally {
      if (recoveryController === ac) {
        recoveryController = null;
        recovering.value = false;
      }
    }
  }

  function cancelRequests() {
    streamController?.abort();
    streamController = null;
    historyController?.abort();
    historyController = null;
    recoveryController?.abort();
    recoveryController = null;
    recovering.value = false;
    status.value = "idle";
    typingId.value = "";
    externalBusy.value = false;
    researchProgress.value = "";
    sending.value = false;
    backgroundRunning.value = false;
  }
  async function stop() {
    const id = threadId.value;
    const version = selection;
    cancelRequests();
    if (id) {
      const result = await chatApi.stopRun(user.userId, id);
      if (result?.stopped && version === selection) {
        const history = await chatApi.messages(user.userId, id);
        if (version === selection && id === threadId.value)
          messages.value = toChatMessages(history.messages, id);
      }
    }
    if (version !== selection) return;
    await recover();
  }
  function clearConversation() {
    metrics.value = null;
    cancelRequests();
    messages.value = [];
    approvals.value = [];
    questions.value = [];
    error.value = null;
    recoveryError.value = null;
    uploads.clear();
    draft.value = "";
  }
  function newThread() {
    if (navigationDisabled.value) return;
    selection++;
    clearConversation();
    threadId.value = null;
    saveActiveThread(user.userId, null);
  }
  async function refreshCurrent() {
    if (loading.value || navigationDisabled.value || busy.value) return false;
    const id = threadId.value;
    const version = selection;
    await refresh();
    if (version !== selection || threadsError.value) return false;
    if (id) await selectThread(id, true);
    return !error.value && !recoveryError.value;
  }
  async function selectThread(id: string, reload = false) {
    if (navigationDisabled.value || (id === threadId.value && !reload)) return;
    const preserveDraft = reload && id === threadId.value;
    const version = ++selection;
    cancelRequests();
    switching.value = true;
    const ac = new AbortController();
    historyController = ac;
    try {
      const run = await chatApi.streamStatus(user.userId, id, ac.signal);
      const result = await chatApi.messages(user.userId, id, ac.signal);
      if (version !== selection || ac.signal.aborted) return;
      if (preserveDraft) {
        // 刷新服务端消息不应丢弃用户尚未发送的输入和上传队列。
        cancelRequests();
        approvals.value = [];
        questions.value = [];
        error.value = null;
        recoveryError.value = null;
      } else clearConversation();
      const restored = toChatMessages(result.messages, id);
      if (run.active) {
        messages.value = restored.slice(0, run.base_count);
        const currentUser = restored.slice(run.base_count).find((item) => item.role === "user");
        if (currentUser) messages.value.push(currentUser);
        else if (run.user_input)
          messages.value.push({
            id: `user-rejoined-${Date.now()}`,
            role: "user",
            content: run.user_input,
          });
      } else messages.value = restored;
      threadId.value = id;
      backgroundRunning.value = run.active || run.state === "running";
      saveActiveThread(user.userId, id);
      if (run.active) void runStream("", [], undefined, true);
      else await recover();
    } catch (issue) {
      if (!ac.signal.aborted && version === selection) error.value = (issue as Error).message;
    } finally {
      if (version === selection) switching.value = false;
    }
  }
  async function initialize() {
    if (initialized) return;
    initialized = true;
    const version = selection;
    switching.value = true;
    await refresh();
    if (version !== selection) return;
    switching.value = false;
    const saved = loadActiveThread(user.userId);
    if (saved && threads.value.some((item) => item.id === saved)) await selectThread(saved);
  }
  async function renameThread(id: string, name: string) {
    if (busy.value || navigationDisabled.value) return;
    managingThread.value = true;
    const version = selection;
    try {
      const updated = await chatApi.rename(user.userId, id, name);
      if (version !== selection) return;
      listVersion++;
      loading.value = false;
      const thread = threads.value.find((item) => item.id === id);
      if (thread) thread.title = updated.title;
    } finally {
      managingThread.value = false;
    }
  }
  async function deleteThread(id: string) {
    if (busy.value || navigationDisabled.value) return;
    managingThread.value = true;
    const version = selection;
    try {
      await chatApi.remove(user.userId, id);
      if (version !== selection) return;
      listVersion++;
      loading.value = false;
      threads.value = threads.value.filter((item) => item.id !== id);
      if (threadId.value === id) {
        selection++;
        clearConversation();
        threadId.value = null;
        saveActiveThread(user.userId, null);
      }
    } finally {
      managingThread.value = false;
    }
  }

  async function runStream(
    text: string,
    attachments: Attachment[],
    resumeRequest?: ResumeRequest,
    follow = false,
    checkpointRecovery?: import("@/api/chat").RecoverRun,
  ) {
    const tid = threadId.value;
    if (!tid || streamController) return;
    const ac = new AbortController();
    streamController = ac;
    let id = `assistant-${Date.now()}`;
    let executionStarted = follow;
    let unpersistedFailure = false;
    const firstMessageIndex = messages.value.length;
    let phase = 0;
    function nextPhase() {
      id = `assistant-${Date.now()}-${++phase}`;
      messages.value.push({ id, role: "assistant", content: "" });
      typingId.value = id;
    }
    if (!resumeRequest && !follow && !checkpointRecovery)
      messages.value.push({
        id: `user-${Date.now()}`,
        role: "user",
        content: text.trim(),
        createdAt: new Date().toISOString(),
        attachments,
      });
    messages.value.push({ id, role: "assistant", content: "" });
    // 审批提交期间保留列表，收到服务端待办后再更新，避免弹窗闪退和失败丢项。
    if (!resumeRequest) {
      questions.value = [];
      approvals.value = [];
    }
    status.value = "submitting";
    researchProgress.value = "";
    error.value = null;
    typingId.value = id;
    try {
      const input = {
        userId: user.userId,
        threadId: tid,
        text,
        attachments,
        resume: resumeRequest,
        recovery: checkpointRecovery,
        signal: ac.signal,
      };
      await (follow ? followChat : streamChat)(input, (event) => {
        if (ac.signal.aborted || streamController !== ac || tid !== threadId.value) return;
        status.value = "streaming";
        if (event.type === "message.start") {
          executionStarted = true;
          return;
        }
        if (event.type === "metrics") {
          metrics.value = event.metrics as import("@/types/chat").SessionMetrics;
          return;
        }
        if (event.type === "stream.truncated") {
          researchProgress.value = "较早的流式输出已折叠，任务结束后会恢复完整消息";
          return;
        }
        if (event.type === "human.pending") {
          approvals.value = (event.approvals as ApprovalInfo[]).filter(
            (item) => item.status === "pending",
          );
          questions.value = (event.questions as QuestionInfo[]).filter(
            (item) => item.status === "pending",
          );
          return;
        }
        let message = messages.value.find((m) => m.id === id);
        if (event.type === "assistant.start") {
          if (
            message &&
            (message.content.trim() ||
              message.reasoning?.trim() ||
              message.artifacts?.length ||
              message.tools?.length)
          )
            nextPhase();
          return;
        }
        // 某些模型会在同一次调用里输出后继续思考，也需要新的承载块。
        if (event.type === "reasoning.delta" && message?.content.trim()) {
          nextPhase();
          message = messages.value.find((m) => m.id === id);
        }
        if (!message) return;
        if (event.type === "question.updated" && event.question) {
          const question = event.question as QuestionInfo;
          questions.value = [
            ...questions.value.filter((q) => q.id !== question.id),
            question,
          ].filter((item) => item.status === "pending");
        } else if (event.type === "approval.updated" && event.approval) {
          const approval = event.approval as ApprovalInfo;
          approvals.value = [
            ...approvals.value.filter((a) => a.id !== approval.id),
            approval,
          ].filter((item) => item.status === "pending");
        } else if (event.type === "message.delta" && typeof event.delta === "string")
          message.content += event.delta;
        else if (event.type === "reasoning.delta" && typeof event.delta === "string")
          message.reasoning = (message.reasoning ?? "") + event.delta;
        else if (event.type === "artifact.created" && event.artifact)
          (message.artifacts ??= []).push(event.artifact);
        else if (event.type === "research.progress" && typeof event.message === "string")
          researchProgress.value = event.message;
        else if (event.type === "tool.start" && typeof event.name === "string") {
          (message.tools ??= []).push({
            id: typeof event.call_id === "string" ? event.call_id : "",
            name: event.name,
            status: "running",
          });
          if (isMcpTool(event.name)) externalBusy.value = true;
        } else if (event.type === "tool.end" && typeof event.name === "string") {
          const running = messages.value
            .slice(firstMessageIndex)
            .flatMap((m) => m.tools ?? [])
            .reverse()
            .find(
              (tool) =>
                tool.name === event.name &&
                tool.status === "running" &&
                (!event.call_id || tool.id === event.call_id),
            );
          if (running) {
            running.status = event.ok === false ? "error" : "success";
            running.result = typeof event.result === "string" ? event.result : "";
          }
          if (isMcpTool(event.name)) externalBusy.value = false;
        } else if (event.type === "error") {
          error.value = event.error ?? "未知错误";
          if (event.failure) {
            message.failure = event.failure as ExecutionFailure;
            unpersistedFailure = !message.failure.persisted;
          }
          for (const item of messages.value.slice(firstMessageIndex)) {
            for (const tool of item.tools ?? []) {
              if (tool.status === "running") {
                tool.status = "interrupted";
                tool.result = "任务中断，未收到工具完成结果。";
              }
            }
          }
        }
      });
    } catch (issue) {
      if (!ac.signal.aborted && streamController === ac) {
        error.value = (issue as Error).message;
      }
    } finally {
      const current = () => !ac.signal.aborted && streamController === ac && tid === threadId.value;
      if (current()) {
        try {
          const run = await recover();
          if (current() && run) {
            if (run.active || run.state === "running") {
              error.value = "连接已断开，任务仍在后台运行。请刷新会话重新连接。";
            } else if (executionStarted && !unpersistedFailure) {
              // SDK run_id 每次恢复都会变化；结束后按已落库的逻辑调用结果校准整段展示。
              // 未开始的请求和未保存的失败只能在本地保留，历史无法还原它们。
              const latest = await chatApi.messages(user.userId, tid, ac.signal);
              if (current()) {
                messages.value = toChatMessages(latest.messages, tid);
              }
            }
          }
        } catch (issue) {
          if (current()) error.value = `对话记录同步失败：${(issue as Error).message}`;
        } finally {
          // 会话切换会中止校准请求；旧请求不能覆盖新流的状态。
          if (current()) {
            streamController = null;
            status.value = error.value ? "error" : "idle";
            typingId.value = "";
            externalBusy.value = false;
            researchProgress.value = "";
          }
        }
      }
    }
    return !ac.signal.aborted;
  }
  async function send() {
    if (!canSend.value) return;
    sending.value = true;
    const version = selection;
    try {
      if (!threadId.value) {
        const created = await chatApi.create(user.userId);
        if (version !== selection) return;
        threads.value.unshift(created);
        threadId.value = created.id;
        saveActiveThread(user.userId, created.id);
      }
      const text = draft.value,
        files = [...uploads.attachments.value];
      draft.value = "";
      uploads.clear();
      await runStream(text, files);
      if (version === selection) await refresh();
    } catch (issue) {
      if (version === selection) error.value = (issue as Error).message;
    } finally {
      if (version === selection) sending.value = false;
    }
  }
  async function resume(request: ResumeRequest) {
    if (busy.value || recovering.value || recoveryError.value || navigationDisabled.value) return;
    sending.value = true;
    const version = selection;
    try {
      await runStream("", [], request);
      if (version === selection) await refresh();
    } finally {
      if (version === selection) sending.value = false;
    }
  }
  async function submitQuestions(requests: ResumeRequest[]) {
    if (busy.value || recovering.value || recoveryError.value || navigationDisabled.value) return;
    questionSubmitting.value = true;
    const tid = threadId.value;
    const version = selection;
    try {
      for (const request of requests) {
        if (tid !== threadId.value) break;
        const completed = await runStream("", [], request);
        if (!completed || error.value || recoveryError.value || version !== selection) break;
      }
      if (tid === threadId.value && !error.value && !questions.value.length) {
        try {
          sessionStorage.removeItem(`astra:questions:${user.userId}:${tid}`);
        } catch {
          /* 存储不可用不影响提交。 */
        }
      }
      if (version === selection) await refresh();
    } finally {
      if (version === selection) questionSubmitting.value = false;
    }
  }
  function reset() {
    selection++;
    listVersion++;
    initialized = false;
    clearConversation();
    threadId.value = null;
    threads.value = [];
    sending.value = false;
    switching.value = false;
    questionSubmitting.value = false;
    loading.value = false;
  }
  onScopeDispose(cancelRequests);
  return {
    threadId,
    metrics,
    interruptedRun,
    resumeInterrupted,
    threads,
    messages,
    approvals,
    questions,
    status,
    error,
    threadsError,
    recoveryError,
    loading,
    switching,
    recovering,
    sending,
    managingThread,
    questionSubmitting,
    draft,
    busy,
    title,
    hasPendingInteraction,
    navigationDisabled,
    canSend,
    typingId,
    externalBusy,
    researchProgress,
    items: uploads.items,
    uploadErrors: uploads.errors,
    addFiles: uploads.addFiles,
    retry: uploads.retry,
    remove: uploads.remove,
    initialize,
    reset,
    refresh,
    refreshCurrent,
    recover,
    stop,
    newThread,
    selectThread,
    renameThread,
    deleteThread,
    send,
    resume,
    submitQuestions,
  };
});
function isMcpTool(name: unknown): boolean {
  return typeof name === "string" && name.startsWith("mcp__");
}
