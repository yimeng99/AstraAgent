# OpenSandbox Docker 管理

本机部署目录：`E:/docker_data/OpenSandbox`。此目录的 `compose.yaml`、
`Dockerfile`、`patch_isolation.py` 和启动脚本来自当前目录。

```powershell
cd E:\docker_data\OpenSandbox
docker compose up -d --build --wait
docker compose ps
docker compose logs --tail 100 server
docker compose restart server
```

管理服务监听 `18080`，自动重启策略为 `unless-stopped`。
原始 `sandbox.toml`、`opensandbox.db` 保留；迁移后的运行配置为
`sandbox.docker.toml`，数据库放在 `docker-state/opensandbox.db`。
宿主机 `~/.opensandbox/metadata/` 的归属、租约和过期记录也迁移到
`docker-state/metadata/` 并持久挂载，保留现有用户绑定。
现有密钥通过本地 `.env.docker` 注入，以上三个运行文件不要提交。
不要同时启动 Windows 版和 Docker 版控制服务。

代理服务加入 Docker 默认 `bridge`，以内部 IP 访问现有用户沙箱。
AstraAgent Docker 后端使用 `SANDBOX_BASE_URL=http://host.docker.internal:18080`
及 `SANDBOX_USE_SERVER_PROXY=true`，避免访问宿主机随机映射端口。
`sandbox.docker.toml` 的 `server.eip` 留空，让代理返回客户端实际访问的
地址、端口与 `/v1` 前缀；固定宿主机 IP 会导致 Docker 后端无法访问。
宿主机 API 如需代理，也可以设置同一开关并使用 `http://localhost:18080`。

镜像固定使用 `opensandbox-server==0.2.3`，保留本机已有的 bwrap
NET_ADMIN 补丁；补丁只作用于显式启用隔离扩展的沙箱。
升级前须复核补丁和执行隔离，构建发现源代码不匹配时会直接失败。

`docker compose down` 只停止控制服务。动态创建的用户沙箱由
OpenSandbox 管理，不是 Compose 的静态服务；本次迁移不重建用户沙箱。
重启或更新前先确认没有活动任务。

官方配置参考：https://github.com/opensandbox-group/OpenSandbox/blob/main/server/configuration.md
