# LLM Provider 适配说明

> 日期：2026-09-24

AstraAgent 通过 :data:`core.llm.PROVIDER_PRESETS` 支持多家 LLM provider。
新加 provider 只需在表里加一行，无需改业务代码。

## 支持的 provider

| provider 名 | 协议 | 适用 | 默认 base_url | 默认模型 |
|-----------|------|------|---------------|----------|
| `openai` | OpenAI | OpenAI 官方 / 兼容服务 | `https://api.openai.com/v1` | `gpt-4o-mini` |
| `MiniMax` | OpenAI | MiniMax Token Plan | `https://api.MiniMax.com/v1` | `MiniMax-M2` |
| `deepseek` | OpenAI | DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| `zhipu` | OpenAI | 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-plus` |
| `moonshot` | OpenAI | Moonshot Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| `anthropic` | Anthropic 原生 | Claude 系列 | （官方） | `claude-3-5-sonnet-latest` |
| `custom` | OpenAI | 自建 / 私有部署 | **必填** | `custom-model` |

## 快速切换

```bash
# 1. 改 .env
LLM_PROVIDER=MiniMax        # 切到 MiniMax Token Plan
LLM_BASE_URL=               # 留空用预设
LLM_MODEL=                  # 留空用预设（MiniMax-M2 / M3 / M4）
LLM_API_KEY=eyJ...

# 2. 启动
uv run python -m core chat
```

## 覆盖优先级

```python
base_url = config.base_url or preset.base_url
model    = config.model    or preset.default_model
```

`LLM_BASE_URL` / `LLM_MODEL` 显式设置会**覆盖**预设；不设置才用预设。

## 添加新 provider

1. 编辑 :file:`src/core/llm.py`，在 :data:`PROVIDER_PRESETS` 加一项：

   ```python
   "new_provider": ProviderPreset(
       display_name="...",
       base_url="https://...",
       default_model="...",
       api_key_format="...",
       notes="...",
   ),
   ```

2. 如使用非 OpenAI 协议（如 Anthropic），需在 :func:`build_llm_client` 加分支，
   并安装对应 SDK：`uv add langchain-anthropic` 等。

3. 更新 :file:`.env.example` 注释 + 本文档的「支持的 provider」表。

## 测试当前配置

```bash
uv run python -m core check
```

输出示例：

```
2026-... [info] llm.client.build provider=MiniMax base_url=https://api.MiniMax.com/v1 ...
AstraAgent 配置 OK。
  LLM: MiniMax/MiniMax-M2
  Feishu: identity=bot（依赖 lark-cli auth login）
  Workspace: workspace
```

`llm.client.build` 这条日志确认了 provider / model / base_url 三件套正确加载。

## 实际试调 MiniMax

如需确认 SDK 真的能联通 MiniMax：

```python
import asyncio
from langchain_openai import ChatOpenAI

async def main():
    client = ChatOpenAI(
        model="MiniMax-M2",
        api_key="<your MiniMax token plan key>",
        base_url="https://api.MiniMax.com/v1",
    )
    resp = await client.ainvoke("你好")
    print(resp.content)

asyncio.run(main())
```

预期：返回中文回复，无 401 / 404。