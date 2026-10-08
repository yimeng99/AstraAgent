# 业务接入规范（business 插件）

> 适用范围：`src/business/` 下的所有业务子包。
> 索引见 [README.md](README.md)。

`business` 是对接企业业务系统（ERP / CRM / OA / 工单 / 订单 …）的唯一落点：
**每个子包 = 一个业务系统**，互不影响、独立演进。

## 目录约定

```
src/business/
├── __init__.py          # 自动发现 + 聚合（本规范实现的机制）
├── crm/                 # ← 一个业务系统
│   ├── __init__.py      # 唯一需要「注册」的地方：导出 TOOLS / SUBAGENTS
│   ├── client.py        # 接入层：HTTP / SDK 客户端
│   ├── tools.py         # 工具层：@tool 封装
│   └── agent.py         # 框架原生 SubAgent 配置
├── oa/
└── erp/
```

## 加一个新业务：只需新建一个子包

**无需改动 `core.agent` 或 `business/__init__.py`** —— 子包会被自动发现。

子包的 `__init__.py` 需导出：

| 名称 | 类型 | 说明 |
|------|------|------|
| `TOOLS` | `tuple[BaseTool, ...]` | 暴露给 LLM 的工具；没有则留空元组 |
| `SUBAGENTS` | `tuple[SubAgent, ...]` | 框架原生字典；没有则留空元组 |
| `close()` | `async () -> None` | **可选**，释放连接池等资源 |

子 Agent 使用 `deepagents.middleware.subagents.SubAgent` 原生字典，不再使用项目自定义 Spec。
`tools` 必须引用主 Agent 已注册的工具实例（业务工具应同时在 `TOOLS` 导出），不接受工具名字字符串。
省略 `tools` 表示继承主 Agent 工具，显式 `tools: []` 表示不额外授予业务工具；框架自带工具仍然存在。
`model`、`skills`、`middleware` 等字段直接传递给框架；服务端保留自定义中间件并追加人工介入保护。
名称重复或引用未注册工具时明确报错，不能静默忽略后扩大工具权限。

三者均为可选，但建议显式写出 `TOOLS` / `SUBAGENTS`（哪怕为空元组），
这样意图清晰，也让 mypy 校验得出来。

```python
# src/business/crm/__init__.py
from __future__ import annotations

from business.crm.agent import CRM_AGENT
from business.crm.tools import query_customer

TOOLS = (query_customer,)
SUBAGENTS = (CRM_AGENT,)
```

## 故障隔离

某个子包导入失败（依赖缺失、配置错误）时，`discover_business()` 会记录日志并
**跳过该业务**，其余业务照常运行 —— 单个业务挂掉不该拖垮整个 agent。

冲突的工具名 / sub-agent 名则**直接抛错**，因为那是真 bug，早失败早发现。

## 安全底线

- 凭证一律进 `.env`，**绝不出现在 prompt / tool docstring / 错误信息里**。
- 写操作（增删改）默认不做。开放前需人工 review，且优先做成**需要显式确认**的
  独立工具，而不是和只读查询混在同一个工具里。
- 工具返回给模型的错误信息统一走 `core.security.safe_error_message`（脱敏）。
