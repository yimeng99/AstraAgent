import { requestApi, requestBlob, userHeaders } from "@/utils/request";
import type { Attachment, SandboxEntry } from "@/types/files";

export async function uploadAttachment(
  file: File,
  userId: string,
  onProgress: (ratio: number) => void,
  signal: AbortSignal,
): Promise<Attachment> {
  const data = new FormData();
  data.append("file", file);
  const result = await requestApi<{
    file_id: string;
    filename: string;
    content_type: string;
    size: number;
    preview_url?: string;
    kind: string;
  }>({
    url: "/upload",
    method: "POST",
    data,
    signal,
    timeout: 180_000,
    headers: userHeaders(userId),
    // Axios 在浏览器用 XHR 上报进度；100% 仅代表发送完成，还需等待服务器校验。
    onUploadProgress: (event) => {
      if (event.total) onProgress(Math.min(0.99, event.loaded / event.total));
    },
  });
  return {
    fileId: result.file_id,
    filename: result.filename,
    contentType: result.content_type,
    size: result.size,
    previewUrl: result.preview_url ?? `/api/v1/files/${result.file_id}`,
    kind: result.kind === "document" ? "file" : "image",
  };
}
const base = (thread: string) => `/threads/${encodeURIComponent(thread)}/sandbox`;
export const filesApi = {
  list: (user: string, thread: string) =>
    requestApi<{ entries: SandboxEntry[] }>({
      url: `${base(thread)}/files`,
      headers: userHeaders(user),
    }),
  upload: (user: string, thread: string, path: string, file: File) => {
    const data = new FormData();
    data.append("file", file);
    return requestApi({
      url: `${base(thread)}/files`,
      params: { path },
      method: "POST",
      data,
      timeout: 180_000,
      headers: userHeaders(user),
    });
  },
  rename: (user: string, thread: string, path: string, name: string) =>
    requestApi({
      url: `${base(thread)}/files`,
      method: "PATCH",
      data: { path, name },
      headers: userHeaders(user),
    }),
  createDirectory: (user: string, thread: string, path: string, name: string) =>
    requestApi({
      url: `${base(thread)}/directories`,
      method: "POST",
      data: { path, name },
      headers: userHeaders(user),
    }),
  remove: (user: string, thread: string, path: string) =>
    requestApi({
      url: `${base(thread)}/files`,
      params: { path },
      method: "DELETE",
      headers: userHeaders(user),
    }),
  content: (user: string, thread: string, path: string, download = false) =>
    requestBlob({
      url: `${base(thread)}/content`,
      params: { path, download },
      timeout: 60_000,
      headers: userHeaders(user),
    }),
};

export async function loadPreview(url: string, signal: AbortSignal): Promise<ArrayBuffer> {
  // blob URL 不走 Axios 的 API baseURL，也不携带用户请求头。
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`读取失败（HTTP ${response.status}）`);
  return response.arrayBuffer();
}
