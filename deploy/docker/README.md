# Docker 部署

复制项目根目录 `.env.example` 为 `.env`，填入模型、PostgreSQL 和可选服务配置。
真实 `.env` 只读挂载到后端，不复制进镜像，也不提交到 Git。

```powershell
docker compose up -d --build
docker compose ps
docker compose logs --tail 100 backend
```

前端监听 `5173`，访问 `http://localhost:5173`。Nginx 将 `/api` 和 `/user`
转发给后端，支持 SSE；后端只在容器网络中开放 `8000`。
API 文档位于 `/api/v1/docs`。

`workspace/` 挂载到 `/app/workspace`，保留上传、会话决策和沙箱绑定。
更新或重启前先确认没有活动任务，避免中断长任务。
不要在同一工作目录上同时运行宿主机后端和容器后端。

配置中需提供容器能够访问的 LLM、PostgreSQL、OpenSandbox 和其他外部服务地址。
容器内的 `localhost` 指向容器自身；访问 Docker Desktop 宿主机可使用
`host.docker.internal`。不要把 Windows 绝对路径作为容器工作目录。

OpenSandbox 的配置和迁移说明见 [OpenSandbox Docker 管理](../opensandbox/README.md)。
后端通过 `SANDBOX_USE_SERVER_PROXY=true` 使用控制服务代理，管理服务的
`server.eip` 留空，避免返回后端容器无法访问的宿主机地址。
用户沙箱由 OpenSandbox 动态管理。

当前项目使用模拟用户和 `X-User-Id`，该请求头不构成身份认证。
部署到公网前请接入实际鉴权并保护 API、上传及文件下载入口。

停止服务（保留工作目录数据）：

```powershell
docker compose down
```
