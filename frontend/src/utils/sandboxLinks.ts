import { API_BASE } from "./request";
import { filesApi } from "@/api/files";
import type { PreviewTarget } from "@/types/files";

export function legacySandboxPaths(content: string): string[] {
  return [
    ...new Set(
      content.match(
        /\/workspace\/sessions\/[a-f0-9]{64}\/[^\n`<>]+?\.(?:xlsx|docx|pdf|png|jpe?g|webp|gif|txt|md|csv|json|zip)(?=$|[\s`"'）)。，])/g,
      ) || [],
    ),
  ];
}

export async function openSandboxLink(
  raw: string,
  thread: string,
  user: string,
): Promise<PreviewTarget | null> {
  let link: URL;
  if (raw.startsWith("/workspace/sessions/")) {
    const hash = [
      ...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(thread))),
    ]
      .map((v) => v.toString(16).padStart(2, "0"))
      .join("");
    const prefix = `/workspace/sessions/${hash}/`;
    if (!raw.startsWith(prefix)) throw new Error("只能打开当前会话的文件");
    link = new URL(
      `${API_BASE}/threads/${encodeURIComponent(thread)}/sandbox/content`,
      location.origin,
    );
    link.searchParams.set("path", raw.slice(prefix.length));
  } else link = new URL(raw, location.origin);
  if (
    link.origin !== location.origin ||
    link.pathname !== `${API_BASE}/threads/${encodeURIComponent(thread)}/sandbox/content`
  )
    throw new Error("文件链接不属于当前会话");
  const path = link.searchParams.get("path");
  if (!path) throw new Error("文件链接缺少路径");
  const filename = path.split("/").pop() || "文件";
  async function download() {
    const blob = await filesApi.content(user, thread, path!, true);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  if (["true", "1"].includes(link.searchParams.get("download") || "")) {
    await download();
    return null;
  }
  const blob = await filesApi.content(user, thread, path);
  return {
    fileId: path,
    filename,
    url: URL.createObjectURL(blob),
    size: blob.size,
    download,
  };
}
