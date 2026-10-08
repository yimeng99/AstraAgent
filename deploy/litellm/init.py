"""初始化独立网关凭证，保留已有值以免数据库密钥失效。"""

import secrets
from pathlib import Path

from dotenv import dotenv_values, set_key

directory = Path(__file__).resolve().parent
target = directory / ".env"
existing = dotenv_values(target)
source = dotenv_values(directory.parents[1] / ".env")

primary = {
    "PRIMARY_MODEL": "openai/" + (source.get("LLM_MODEL") or "MiniMax-M3"),
    "PRIMARY_API_BASE": source.get("LLM_BASE_URL") or "https://api.minimaxi.com/v1",
    "PRIMARY_API_KEY": source.get("LLM_API_KEY") or "",
}
if not existing.get("PRIMARY_API_KEY") and not primary["PRIMARY_API_KEY"]:
    raise SystemExit("请先填写项目 .env 的 LLM_API_KEY，或手动填写网关 .env。")
if not existing.get("PRIMARY_API_KEY") and source.get("LLM_PROVIDER", "").lower() == "anthropic":
    raise SystemExit("此初始化脚本只复制 OpenAI 兼容渠道，请手动配置 Anthropic。")

for key in ("POSTGRES_PASSWORD", "LITELLM_MASTER_KEY", "LITELLM_SALT_KEY", "UI_PASSWORD"):
    if not existing.get(key):
        value = secrets.token_hex(32)
        if key == "LITELLM_MASTER_KEY":
            value = "sk-" + value
        set_key(target, key, value)
for key, value in primary.items():
    if not existing.get(key):
        set_key(target, key, value)

print("已准备 deploy/litellm/.env；凭证不输出，项目模型配置未切换。")
