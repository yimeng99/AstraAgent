import type { ArtifactInfo } from "@/types/chat";
// ── 私有：SSE 解析器 ─────────────────────────────────

export type ParsedEvent = {
  type: string;
  delta?: string;
  error?: string;
  thread_id?: string;
  artifact?: ArtifactInfo;
  [k: string]: unknown;
};

export async function consumeSse(
  body: ReadableStream<Uint8Array>,
  onEvent: (ev: ParsedEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");

  // 按 SSE 规范：每个事件由若干 field 行 + 空行组成
  let buf = "";
  let eventBuf = ""; // 当前事件的 data 累计
  let eventId: string | undefined;

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      // 按行扫
      while (true) {
        const lf = buf.indexOf("\n");
        if (lf === -1) break;
        const line = buf.slice(0, lf).replace(/\r$/, ""); // 去 \r
        buf = buf.slice(lf + 1);

        if (line === "") {
          // 空行 = 事件结束；没有累积到任何 data 的空行（心跳/分隔）不派发空事件
          if (eventBuf !== "" || eventId !== undefined) {
            try {
              const payload = JSON.parse(eventBuf || "{}") as ParsedEvent;
              onEvent(payload);
            } catch {
              /* 忽略非 JSON */
            }
            eventBuf = "";
            eventId = undefined;
          }
          continue;
        }

        // 按 SSE 字段名解析
        const colon = line.indexOf(":");
        if (colon === -1) continue;
        const field = line.slice(0, colon);
        let value = line.slice(colon + 1);
        if (value.startsWith(" ")) value = value.slice(1);

        if (field === "data") {
          eventBuf = eventBuf === "" ? value : eventBuf + "\n" + value;
        } else if (field === "id") {
          eventId = value;
        }
        // event / retry / 其他字段：忽略
      }
    }
  } finally {
    reader.releaseLock?.();
  }
}
