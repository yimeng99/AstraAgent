import { requestApi, API_BASE, userHeaders, checkResponse } from "@/utils/request";
import { consumeSse } from "@/utils/sse";
import type { ParsedEvent } from "@/utils/sse";
import type {
  ThreadSummary,
  ThreadMessage,
  ApprovalInfo,
  QuestionInfo,
  ResumeRequest,
} from "@/types/chat";
import type { Attachment } from "@/types/files";

export interface RunState {
  active: boolean;
  base_count: number;
  user_input: string;
  state: string;
  recoverable: boolean;
  requires_tool_confirmation: boolean;
  checkpoint_id: string;
}
export interface RecoverRun { checkpoint_id: string; retry_tools: boolean }

export const chatApi = {
  list: (user: string) =>
    requestApi<ThreadSummary[]>({ url: "/threads", headers: userHeaders(user) }),
  create: (user: string) =>
    requestApi<ThreadSummary>({
      url: "/threads",
      method: "POST",
      data: {},
      headers: userHeaders(user),
    }),
  rename: (user: string, id: string, title: string) =>
    requestApi<ThreadSummary>({
      url: `/threads/${encodeURIComponent(id)}`,
      method: "PATCH",
      data: { title },
      headers: userHeaders(user),
    }),
  remove: (user: string, id: string) =>
    requestApi<void>({
      url: `/threads/${encodeURIComponent(id)}`,
      method: "DELETE",
      headers: userHeaders(user),
    }),
  messages: (user: string, id: string, signal?: AbortSignal) =>
    requestApi<{ messages: ThreadMessage[] }>({
      url: `/threads/${encodeURIComponent(id)}/messages`,
      headers: userHeaders(user),
      signal,
    }),
  interactions: (user: string, id: string, signal?: AbortSignal) =>
    requestApi<{ approvals: ApprovalInfo[]; questions: QuestionInfo[] }>({
      url: `/threads/${encodeURIComponent(id)}/interactions`,
      headers: userHeaders(user),
      signal,
    }),
  streamStatus: (user: string, id: string, signal?: AbortSignal) =>
    requestApi<RunState>({
      url: `/threads/${encodeURIComponent(id)}/stream/status`,
      headers: userHeaders(user),
      signal,
    }),
  stopRun: (user: string, id: string) =>
    requestApi<{ stopped: boolean }>({
      url: `/threads/${encodeURIComponent(id)}/stream`,
      method: "DELETE",
      headers: userHeaders(user),
    }),
};

export async function followChat(
  input: { userId: string; threadId: string; signal: AbortSignal },
  onEvent: (event: ParsedEvent) => void,
) {
  const response = await fetch(`${API_BASE}/threads/${encodeURIComponent(input.threadId)}/stream`, {
    headers: userHeaders(input.userId),
    signal: input.signal,
  });
  await checkResponse(response);
  if (!response.body) throw new Error("响应体为空");
  await consumeSse(response.body, onEvent);
}

// 浏览器 Axios 不提供逐帧 ReadableStream；SSE 在接口层保留 fetch，不让组件接触传输细节。
export async function streamChat(
  input: {
    userId: string;
    threadId: string;
    text: string;
    attachments: Attachment[];
    resume?: ResumeRequest;
    recovery?: RecoverRun;
    signal: AbortSignal;
  },
  onEvent: (event: ParsedEvent) => void,
) {
  const response = await fetch(
    input.recovery
      ? `${API_BASE}/threads/${encodeURIComponent(input.threadId)}/recover`
      : input.resume
      ? `${API_BASE}/threads/${encodeURIComponent(input.threadId)}/resume`
      : `${API_BASE}/chat/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...userHeaders(input.userId),
        "X-Thread-Id": input.threadId,
      },
      body: JSON.stringify(
        input.recovery ?? input.resume ?? {
          user_input: input.text.trim(),
          thread_id: input.threadId,
          include_tool_events: true,
          attachments: input.attachments.map((file) => ({
            file_id: file.fileId,
            filename: file.filename,
            content_type: file.contentType,
          })),
        },
      ),
      signal: input.signal,
    },
  );
  await checkResponse(response);
  if (!response.body) throw new Error("响应体为空");
  await consumeSse(response.body, onEvent);
}
