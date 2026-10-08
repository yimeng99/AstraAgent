# Workspace（运行时工作目录）

AstraAgent 的**运行时文件系统上下文**：输入、产出、记忆、计划、工具缓存、日志都落在这里。

每个 session 独立子目录（默认 `per_session` 隔离模式），跑完可单独清理、归档或删除。

---

## 目录结构

```
workspace/
├── config.yaml                # 工作目录配置（保留，将来加载）
├── shared/                    # 跨 session 共享
│   ├── knowledge/             # 知识库（飞书文档缓存、参考材料）
│   ├── prompts/               # 自定义提示词模板
│   └── tools/                 # 共享工具产物
└── sessions/
    └── <session_id>/          # 每个 session 一个独立子目录
        ├── input/             # 用户上传、初始材料
        ├── output/            # agent 产出（报告、文件、代码）
        ├── scratch/           # 临时草稿（24h 自动清理）
        ├── plans/
        │   └── todo.md        # Plan / Todo 持久化
        ├── memory/            # 长期记忆
        │   ├── short_term.json
        │   ├── observations.jsonl
        │   └── facts.jsonl
        ├── tool_cache/        # 工具结果缓存（按 URL/参数 hash）
        ├── artifacts/         # 中间产物（图表、PDF、解析结果）
        └── logs/
            ├── session.log    # 运行日志
            └── tool_calls.jsonl  # 工具调用审计
```

---

## 子目录用途

| 目录 | 用途 | 是否入 git |
|------|------|-----------|
| `shared/knowledge/` | 知识库（飞书文档缓存） | 否（运行时数据） |
| `shared/prompts/` | 自定义提示词 | 否 |
| `shared/tools/` | 共享工具产物 | 否 |
| `sessions/<id>/input/` | 用户输入材料 | 否 |
| `sessions/<id>/output/` | agent 产出 | 否 |
| `sessions/<id>/scratch/` | 临时草稿 | 否（自动清理） |
| `sessions/<id>/plans/` | 任务计划（todo.md） | 否 |
| `sessions/<id>/memory/` | 短期/长期记忆 | 否 |
| `sessions/<id>/tool_cache/` | 工具结果缓存 | 否 |
| `sessions/<id>/artifacts/` | 中间产物 | 否 |
| `sessions/<id>/logs/` | session 日志 + 工具审计 | 否 |

> 所有 `sessions/*/...` 内容已通过 `.gitignore` 屏蔽，仅保留目录骨架与 `.gitkeep`。

---

## 隔离模式

| 模式 | 行为 |
|------|------|
| `per_session`（默认）| 每个 session 独立目录，互不干扰 |
| `shared`            | 所有 session 共享一个目录（测试 / 调试用）|

在 `.env` 设置 `AGENT_WORKSPACE_SESSION_ISOLATION=shared` 可切换。

---

## 清理策略

- `scratch/`：每次 session 开始清空
- 整个 session：默认保留 30 天（`WorkspaceConfig.retention_days = 30`）
- `retention_days = 0`：永不过期（开发调试用）

---

## 引用

详见 [`docs/design/project-layout.md` §5](../docs/design/project-layout.md)。