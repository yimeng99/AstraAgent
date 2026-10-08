import type { ExecutionFailure } from "@/types/chat";

export function failureMessage(failure: ExecutionFailure): string {
  const { reason, error_type, stage, message } = failure;
  if (reason === "user_stop") return "已停止";
  if (reason === "server_shutdown") return "服务重启或关闭导致执行中断";
  if (reason === "lease_lost") return "执行连接中断";
  if (error_type === "GraphRecursionError") return "已达到本轮执行步数上限，可恢复任务继续";
  // 历史 provider 错误保留原值，展示时统一使用用户能够理解的原因。
  if (/timeout|timed\s*out/i.test(`${error_type} ${message}`))
    return stage === "model" ? "模型响应超时" : "操作超时";
  if (error_type === "CancelledError") return "任务执行中断";
  if (stage === "model") return "模型响应失败";
  if (stage === "tool") return "工具执行失败";
  if (stage === "input") return "输入处理失败";
  return "任务执行失败";
}

export function failureTime(occurredAt: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(new Date(occurredAt));
}
