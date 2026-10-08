/** localStorage 的安全读写。
 *
 * 隐私模式 / 存了坏 JSON / 配额满，一律静默回落 —— 存不下最多是丢状态，
 * 绝不能因此让页面白屏。原先这段 try/catch 在四处各写一遍。
 */

export function readString(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** value 传 null 表示删除。 */
export function writeString(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* 存不了就算了 */
  }
}

export function readJSON<T>(key: string): T | null {
  const raw = readString(key);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

const ACTIVE_THREAD_PREFIX = "astra.active_thread.";

/**
 * 「当前选中的对话」按用户分开存。
 *
 * 必须持久化：threadId 只活在内存里的话，刷新后首屏 effect 会以为"没有选中
 * 对话"而新建一条 —— 侧边栏于是越刷越多"（空对话）"。
 */
export function loadActiveThread(userId: string): string | null {
  return readString(ACTIVE_THREAD_PREFIX + userId) || null;
}

export function saveActiveThread(userId: string, threadId: string | null): void {
  writeString(ACTIVE_THREAD_PREFIX + userId, threadId);
}
