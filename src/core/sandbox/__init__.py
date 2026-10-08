"""沙箱使用入口（先读 service.py，再按需要看执行与文件）。

调用链：
    API/工具 → files.operate_file 或 runtime.execute_python
             → registry.get_sandbox_manager().acquire(context)
             → provisioning.get_or_create_sandbox → OpenSandbox

service.py：用户锁、获取沙箱、释放占用、查询状态，无用户实例缓存。
repository.py：PostgreSQL 归属与锁；只读检查旧 SQLite，不再写入。
provisioning.py：创建/连接/恢复，挂载开关、远端归属、skills 初始化。
sessions.py：会话路径和 namespace 隔离，禁止访问其他会话。
runtime.py：执行 Python，将 SDK 响应转为普通字典。
files.py：文件面板的列出、读取、上传、重命名和删除。
backend.py：复用 Deep Agents BaseSandbox，提供模型文件协议。
attachments/artifacts/file_links：上传存储、报表和下载链接的业务适配。
skills.py：初始化技能文件；tools.py：模型工具定义。

示例（context 来自服务端认证，thread_id 必须属于该用户）：
    execute_python(context, thread_id, "print(1 + 1)", timeout=20)
    operate_file(context, thread_id, "list", "")
    operate_file(context, thread_id, "read", "artifacts/report.docx")

配置：
    POSTGRES_URL：共享归属数据库。
    SANDBOX_BASE_URL：OpenSandbox 控制面。
    SANDBOX_VOLUME_ENABLED=false：默认不挂宿主机卷。
    SANDBOX_VOLUME_ROOT：开启挂载时的共享存储根目录。

旧 SQLite 用户在未启用挂载时可原地迁移已暂停且归属匹配的环境，原文件不删除。
启用挂载或旧环境运行状态不明确时拒绝自动迁移。
操作超时保留远端占用标记，避免并发接管未知状态的操作。
当前没有独立 Worker、共享空闲回收和集群容量调度；
旧的进程内清理线程不适用于 PostgreSQL 用户流程，已移除。
"""
