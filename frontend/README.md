# Astra Agent 前端

Vue 3 + TypeScript + Vite + Element Plus。开发服务器的 `/api` 代理到 `localhost:8000`。

应用样式使用 Sass（SCSS），入口为 `src/index.scss`，由 Vite 编译。

聊天 Markdown 使用 `markstream-vue`，代码块增强使用 `stream-diffs`；实时回复传入流式状态，
历史回复按已完成内容渲染。原始 HTML 按文本转义，SSE 和审批事件仍由现有请求层处理。

```powershell
pnpm install
pnpm dev
pnpm lint          # ESLint 检查 Vue / TypeScript，警告也视为失败
pnpm lint:fix      # 自动修复可处理的问题
pnpm format        # Prettier 格式化
pnpm format:check  # 只检查格式
pnpm check         # lint + 格式检查 + 类型检查
pnpm typecheck
pnpm test
pnpm build
```

`src/App.vue` 编排会话页面；`useChatStream.ts`、`useThreads.ts`、`useAttachments.ts` 管理请求与 Vue 状态。
`sse.ts` 保留逐行 SSE 解析，`history.ts` 保留工具调用前后不同模型回复的边界。
文件预览支持图片、PDF、文本和 Excel；Word 提供下载。用户信息沿用本地存储，不提供切换入口。
生产环境需要将 `/api` 反向代理到后端，`dist/` 为构建产物。
