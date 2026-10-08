import { ref, computed, onScopeDispose } from "vue";
import { uploadAttachment } from "@/api/files";
import type { UploadItem } from "@/types/files";
import {
  EXT_SET,
  IMAGE_EXT,
  MAX_IMAGE_BYTES,
  MAX_DOC_BYTES,
  MAX_FILES,
  extOf,
  formatSize,
} from "@/utils/files";
const MAX_CONCURRENCY = 3;
/** crypto.randomUUID 在非安全上下文（http 局域网）里可能没有，兜底一下 */
function newId(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function sameFile(a: File, b: File): boolean {
  return a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;
}

export function useAttachmentQueue(userId: () => string) {
  const items = ref<UploadItem[]>([]);
  const errors = ref<string[]>([]);
  let disposed = false;
  const controllers = new Map<string, AbortController>();
  async function startUpload(id: string) {
    const item = items.value.find((i) => i.id === id);
    if (!item || disposed) return;
    item.status = "uploading";
    item.error = undefined;
    item.progress = 0;
    const controller = new AbortController();
    controllers.set(id, controller);
    try {
      const result = await uploadAttachment(
        item.file,
        userId(),
        (ratio) => {
          item.progress = ratio;
        },
        controller.signal,
      );
      if (disposed || !items.value.some((i) => i.id === id)) return;
      item.attachment = result;
      item.status = "done";
      item.progress = 1;
    } catch (e) {
      if (controller.signal.aborted) return;
      item.status = "error";
      item.error = (e as Error).message;
    } finally {
      if (controllers.get(id) === controller) controllers.delete(id);
    }
  }
  async function addFiles(files: FileList | File[]) {
    const accepted: File[] = [];
    errors.value = [];
    for (const file of Array.from(files)) {
      const ext = extOf(file.name);
      if (!EXT_SET.has(ext)) {
        errors.value.push(`${file.name}：不支持的文件类型`);
        continue;
      }
      const limit = IMAGE_EXT.has(ext) ? MAX_IMAGE_BYTES : MAX_DOC_BYTES;
      if (file.size > limit) {
        errors.value.push(`${file.name}：超过 ${formatSize(limit)} 上限`);
        continue;
      }
      if (
        items.value.some((i) => sameFile(i.file, file)) ||
        accepted.some((i) => sameFile(i, file))
      ) {
        errors.value.push(`${file.name}：文件重复`);
        continue;
      }
      if (items.value.length + accepted.length >= MAX_FILES) {
        errors.value.push(`最多上传 ${MAX_FILES} 个文件`);
        continue;
      }
      accepted.push(file);
    }
    const created: UploadItem[] = accepted.map((file) => ({
      id: newId(),
      file,
      filename: file.name,
      size: file.size,
      kind: IMAGE_EXT.has(extOf(file.name)) ? "image" : "file",
      localUrl: URL.createObjectURL(file),
      status: "uploading",
      progress: 0,
    }));
    items.value.push(...created);
    const queue = created.map((i) => i.id);
    await Promise.all(
      Array.from({ length: Math.min(MAX_CONCURRENCY, queue.length) }, async () => {
        for (;;) {
          const id = queue.shift();
          if (!id || disposed) return;
          await startUpload(id);
        }
      }),
    );
  }
  function remove(id: string) {
    controllers.get(id)?.abort();
    controllers.delete(id);
    const item = items.value.find((i) => i.id === id);
    if (item) URL.revokeObjectURL(item.localUrl);
    items.value = items.value.filter((i) => i.id !== id);
  }
  function clear() {
    controllers.forEach((controller) => controller.abort());
    controllers.clear();
    items.value.forEach((i) => URL.revokeObjectURL(i.localUrl));
    items.value = [];
    errors.value = [];
  }
  onScopeDispose(() => {
    disposed = true;
    clear();
  });
  return {
    items,
    errors,
    attachments: computed(() => items.value.flatMap((i) => (i.attachment ? [i.attachment] : []))),
    uploading: computed(() => items.value.some((i) => i.status === "uploading")),
    addFiles,
    retry: startUpload,
    remove,
    clear,
  };
}
