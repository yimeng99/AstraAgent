# Docs

项目文档根目录。所有非代码的设计、规则、笔记、对接文档都放在这里。

> AI 协作者请先读仓库根的 [AGENTS.md](../AGENTS.md)（入口与硬规矩）；
> 本目录是它的细节展开。

## 目录结构

| 子目录 | 用途 |
|--------|------|
| [`design/`](./design/) | **项目设计规约**（硬性）— 语法、命名、目录、架构、数据建模、业务接入 |
| [`rules/`](./rules/) | 项目规则与约定（环境、依赖、Git / 提交规范） |
| [`notes/`](./notes/) | 开发笔记（初始化、命令速查、LLM provider） |

## 文件索引

```
docs/
├── README.md                # 本文件
├── design/
│   ├── README.md
│   ├── coding-style.md      # 语法、命名、类型、import、docstring、日志
│   ├── project-layout.md    # 目录结构、src/ layout、文件命名
│   ├── architecture.md      # 分层、依赖注入、配置、可观测性
│   ├── data-modeling.md     # 字段命名、对象选型（Pydantic/dataclass/Enum/Protocol/ABC）
│   └── business-plugins.md  # 业务系统接入契约（business/ 子包规范）
├── rules/
│   ├── README.md
│   ├── project-rules.md
│   └── commit-conventions.md  # Conventional Commits + 中文标题
└── notes/
    ├── README.md
    ├── uv-init.md           # uv 初始化记录
    ├── build-run.md         # 启动 / 构建 / 依赖命令
    └── llm-providers.md     # 各 provider 与预设
```

## 约定

- 文档命名：小写连字符（`kebab-case`），如 `project-rules.md`。
- 每个子目录都有自己的 `README.md` 作为索引。
- **临时产物不要进 `docs/`** —— 一次性脚本、截图、验证输出放 `.cache/`
  （见 [AGENTS.md](../AGENTS.md) §3）。`docs/` 只留能长期指导开发的内容。

## 实施计划

- [Agent 执行设计与重构边界](./design/agent-execution.md)
- [Agent 能力完善计划](./notes/agent-roadmap.md)
