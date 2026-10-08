/** HTTP 与 SSE 共用响应契约，业务 API 负责选择传输方式。 */

/** 开发时由 Vite 代理到 :8000（见 vite.config.ts 的 server.proxy） */
export const API_BASE = "/api/v1";

/** 后端按这个头做数据隔离，见 src/api/deps.py */
export const USER_ID_HEADER = "X-User-Id";

/** 带身份的请求头（不含 Content-Type，由调用方按需补）。 */
export function userHeaders(userId: string): Record<string, string> {
  return { [USER_ID_HEADER]: userId };
}

export type ApiResult<T> = { code: string; message: string; data: T };
export const SUCCESS_CODE = "0";

export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** HTTP 成功也必须检查业务 code。 */
export function unwrapApi<T>(body: unknown, status = 200): T {
  const result = body as Partial<ApiResult<T>> | null;
  if (status < 200 || status >= 300 || result?.code !== SUCCESS_CODE) {
    throw new ApiError(
      typeof result?.message === "string" ? result.message : `请求失败（HTTP ${status}）`,
      typeof result?.code === "string" ? result.code : String(status),
      status,
    );
  }
  if (!("data" in result)) throw new ApiError("接口返回格式不正确", "INVALID_RESPONSE", status);
  return result.data as T;
}

export async function readApi<T>(response: Response): Promise<T> {
  const body: unknown = await response.json().catch(() => null);
  return unwrapApi<T>(body, response.status);
}

/** SSE 和文件成功响应不能读取 JSON，否则会消耗流或破坏文件内容。 */
export async function checkResponse(response: Response): Promise<void> {
  if (!response.ok) await readApi(response);
}
