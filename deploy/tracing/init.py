"""生成本机部署凭证；重复执行保留原值，避免已有数据无法解密。"""

import argparse
import secrets
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values, set_key

parser = argparse.ArgumentParser()
parser.add_argument("--activate", action="store_true", help="平台就绪后切换项目 .env")
args = parser.parse_args()
directory = Path(__file__).resolve().parent
target = directory / ".env"
values = dotenv_values(target)
for key in (
    "POSTGRES_PASSWORD",
    "SALT",
    "ENCRYPTION_KEY",
    "CLICKHOUSE_PASSWORD",
    "REDIS_AUTH",
    "MINIO_ROOT_PASSWORD",
    "NEXTAUTH_SECRET",
    "ADMIN_PASSWORD",
):
    if not values.get(key):
        set_key(target, key, secrets.token_hex(32), quote_mode="never")
for key, prefix in (("LANGFUSE_PUBLIC_KEY", "pk-lf-"), ("LANGFUSE_SECRET_KEY", "sk-lf-")):
    if not values.get(key):
        set_key(target, key, prefix + str(uuid4()), quote_mode="never")
if args.activate:
    values = dotenv_values(target)
    root_env = directory.parents[1] / ".env"
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        set_key(root_env, key, values[key], quote_mode="never")
    for key, value in {
        "AGENT_TRACING_ENABLED": "true",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://localhost:3100/api/public/otel/v1/traces",
        "LANGSMITH_TRACING": "false",
    }.items():
        set_key(root_env, key, value, quote_mode="never")
print("Local configuration prepared; credentials remain in deploy/tracing/.env")
