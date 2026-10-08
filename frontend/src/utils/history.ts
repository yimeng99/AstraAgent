import type { ChatMessage } from "@/types/chat";
import type { ThreadMessage } from "@/types/chat";

/** 后端历史 → 前端消息（丢掉 system/tool，保留思维链、产物与用户附件） */
export function toChatMessages(loaded: ThreadMessage[], threadId: string): ChatMessage[] {
  // 保留每次模型调用的消息边界，工具前后的思考与输出不能重排。
  return loaded
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m, i) => ({
      id: m.id || `h-${threadId}-${i}`,
      role: m.role as "user" | "assistant",
      content: m.content,
      createdAt: m.created_at ?? undefined,
      failure: m.failure ?? undefined,
      reasoning: m.reasoning || undefined,
      tools: m.tools?.length ? m.tools : undefined,
      artifacts: m.artifacts?.length ? m.artifacts : undefined,
      // 后端把附件清单藏在消息标记里保存，回显时还原成前端 Attachment 形状
      attachments: m.attachments?.length
        ? m.attachments.map((a) => ({
            fileId: a.file_id,
            filename: a.filename,
            contentType: a.content_type ?? "",
            size: a.size, // 清单里没有大小 → 卡片不显示体积
            previewUrl: a.url,
            kind: a.kind === "image" ? ("image" as const) : ("file" as const),
          }))
        : undefined,
    }));
}
