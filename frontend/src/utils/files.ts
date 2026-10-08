/**
 * 允许的扩展名（与后端 :mod:`core.documents` 的白名单一致）。按**扩展名**判断而非
 * MIME：Windows 上 ``.csv`` 被报成 ``application/vnd.ms-excel``、``.md`` 是空字符串，
 * 靠 MIME 会把用户拦在门外；真正的类型校验在后端按魔数做。
 */
export const ACCEPTED_EXT = [
  "png",
  "jpg",
  "jpeg",
  "webp",
  "gif",
  "pdf",
  "docx",
  "xlsx",
  "txt",
  "md",
  "csv",
  "json",
] as const;

export const EXT_SET = new Set<string>(ACCEPTED_EXT);
export const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "webp", "gif"]);

/** ``<input accept>`` 用 */
export const ACCEPT_ATTR = ACCEPTED_EXT.map((e) => `.${e}`).join(",");

export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
export const MAX_DOC_BYTES = 20 * 1024 * 1024;
/** 单条消息的附件数量上限（再多模型也吃不下，还拖慢上传） */
export const MAX_FILES = 6;

/** 取扩展名（小写，不含点）。附件类型判断全走它，别在各处再写一遍 split(".") */
export function extOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
}

/** 人类可读体积。拿不到大小（例如历史消息只有附件清单）时返回空串。 */
export function formatSize(bytes?: number): string {
  if (bytes === undefined || !Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
