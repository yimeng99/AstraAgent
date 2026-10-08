export type Attachment = {
  /** 后端 file_id —— 发消息时只回传这个，不要传本地路径 */
  fileId: string;
  filename: string;
  contentType: string;
  /** 后端历史里的附件清单不带大小 → 可选，界面按"未知"处理（不显示体积） */
  size?: number;
  previewUrl: string;
  /** ``image`` 可直接预览；``file`` 只展示文件名（后端会抽文本） */
  kind: "image" | "file";
};

/** 上传条目的状态机：uploading → done | error（error 可 retry 回到 uploading） */
export type UploadStatus = "uploading" | "done" | "error";

/**
 * 附件列表里的一格：每个文件**各自**的进度与失败原因（不是一个全局 boolean）。
 * ``file`` 一直留着，失败后原样重传，不必让用户重新选文件。
 */
export type UploadItem = {
  /** 本地条目 id —— 上传中还没有 file_id，UI 的 key / 移除都靠它 */
  id: string;
  file: File;
  filename: string;
  size: number;
  kind: "image" | "file";
  /** 本地缩略图 objectURL，上传中也立刻能看到图（卸载/移除时 revoke） */
  localUrl: string;
  status: UploadStatus;
  /** 0~1；``null`` 表示总长未知，UI 退化成不确定进度条 */
  progress: number | null;
  attachment?: Attachment;
  error?: string;
};

export type PreviewTarget = {
  fileId: string;
  filename: string;
  url: string;
  size?: number;
  text?: string;
  download?: () => Promise<void>;
};

export type SandboxEntry = {
  name: string;
  path: string;
  directory: boolean;
  size: number;
  modified_at: number;
};
