import axios from "axios";
import type { AxiosRequestConfig } from "axios";
import { API_BASE, ApiError, USER_ID_HEADER, unwrapApi } from "./api";
import { useUserStore } from "@/stores/user";

export const http = axios.create({ baseURL: API_BASE, timeout: 15_000 });

// 每次发送时读取当前身份，避免切换用户后仍使用初始化时的请求头。
function withUserHeaders(config: AxiosRequestConfig): AxiosRequestConfig {
  const userId = useUserStore().userId;
  return axios.mergeConfig({ headers: userId ? { [USER_ID_HEADER]: userId } : {} }, config);
}

export async function requestApi<T>(config: AxiosRequestConfig): Promise<T> {
  try {
    const response = await http.request(withUserHeaders(config));
    if (response.status === 204) return undefined as T;
    return unwrapApi<T>(response.data, response.status);
  } catch (error) {
    if (axios.isCancel(error) || !axios.isAxiosError(error)) throw error;
    if (error.response) return unwrapApi<T>(error.response.data, error.response.status);
    throw new ApiError(
      error.code === "ECONNABORTED"
        ? "请求超时，请检查后台服务并重试"
        : "网络请求失败，请检查后台服务",
      error.code || "NETWORK_ERROR",
      0,
    );
  }
}

/** 二进制成功响应保持字节内容；失败响应仍按统一业务契约解释。 */
export async function requestBlob(config: AxiosRequestConfig): Promise<Blob> {
  try {
    const response = await http.request<Blob>({ ...withUserHeaders(config), responseType: "blob" });
    return response.data;
  } catch (error) {
    if (axios.isCancel(error) || !axios.isAxiosError(error)) throw error;
    if (error.response) {
      let data: unknown = error.response.data;
      if (data instanceof Blob) {
        try {
          data = JSON.parse(await data.text());
        } catch {
          data = null;
        }
      }
      return unwrapApi<never>(data, error.response.status);
    }
    throw new ApiError(
      error.code === "ECONNABORTED" ? "文件请求超时" : "网络请求失败",
      error.code || "NETWORK_ERROR",
      0,
    );
  }
}
