import type { Attachment } from "./files";

export type ExecutionFailure = {
  reason?: string;
  id: string;
  occurred_at: string;
  error_type: string;
  message: string;
  stage: string;
  tool_name: string;
  request_id: string;
  persisted: boolean;
  input?: string;
};
/** 助手产出的文件（报表 / 文档），后端 `artifact.created` 事件与历史接口都会给 */
export type ArtifactInfo = {
  file_id: string;
  filename: string;
  size: number;
  content_type: string;
  /** 下载地址（本地后端是 /api/v1/files/{file_id}） */
  url: string;
  kind: string;
};

/** 消息（与后端 SSEEvent 解耦后的简化类型） */
export type ChatMessage = {
  createdAt?: string;
  id: string;
  role: "user" | "assistant";
  content: string;
  /**
   * MiniMax 的 ``<think>`` 段（``reasoning.delta``）：只展示、不发送
   */
  reasoning?: string;
  tools?: {
    id: string;
    name: string;
    status: "running" | "success" | "error" | "interrupted";
    result?: string;
  }[];
  artifacts?: ArtifactInfo[];
  attachments?: Attachment[];
  failure?: ExecutionFailure;
};

export type ApprovalInfo = {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  status: string;
  expires_at: number | null;
  resume_ready?: boolean;
};

export type QuestionInfo = {
  id: string;
  thread_id: string;
  question: string;
  options: string[];
  status: string;
  expires_at: number | null;
  resume_ready?: boolean;
};

export type ResumeRequest =
  | { id: string; approve?: boolean; answer?: string }
  | { ids: string[]; approve: boolean };

export type StreamStatus = "idle" | "submitting" | "streaming" | "error";

export interface SessionMetrics {
  model_calls: number;
  tool_calls: number;
  steps: number;
  model_seconds: number;
  tool_seconds: number;
  input_tokens: number;
  output_tokens: number;
  usage_calls: number;
  total_tokens: number | null;
  ttft: number | null;
  tps: number | null;
  cache_hit_rate: number | null;
  context_percent: number | null;
}

export type ThreadSummary = {
  id: string;
  title: string;
  updated_at: string | null;
  message_count: number;
};

/**
 * 用户消息里回挂的附件（见后端 `api/routes/chat.py` 的附件清单）。
 *
 * 注意 **没有 `size`** —— 清单里只存 file_id / 文件名 / 类型 / 下载地址，
 * 所以体积是可选的：历史附件卡片不显示大小，别按必填类型用（否则界面会出现 NaN）。
 */
export type HistoryAttachment = {
  file_id: string;
  filename: string;
  kind: string;
  content_type?: string;
  url: string;
  size?: number;
};

export type ThreadMessage = {
  created_at?: string | null;
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  failure?: ExecutionFailure | null;
  /** 模型思维链（后端已从 content 里拆出），没有则为空串 */
  reasoning?: string;
  tools?: NonNullable<ChatMessage["tools"]>;
  /** 该轮生成的文件（后端从产物日志挂回来的） */
  artifacts?: ArtifactInfo[];
  /** 用户消息带的附件 */
  attachments?: HistoryAttachment[];
};
