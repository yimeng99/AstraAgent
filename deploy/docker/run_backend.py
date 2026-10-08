"""Adapt host service addresses without rewriting the shared dotenv file."""

import argparse
import os
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

parser = argparse.ArgumentParser()
parser.add_argument("--postgres-host")
parser.add_argument("--sandbox-host")
args = parser.parse_args()
load_dotenv("/app/.env", override=False)

for name, host in (
    ("POSTGRES_URL", args.postgres_host),
    ("POSTGRES_STORE_URL", args.postgres_host),
    ("SANDBOX_BASE_URL", args.sandbox_host),
):
    value = os.environ.get(name)
    if not host or not value:
        continue
    parsed = urlsplit(value)
    # Keep percent-encoded credentials intact; never print connection strings.
    credentials = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
    port = f":{parsed.port}" if parsed.port else ""
    os.environ[name] = urlunsplit(parsed._replace(netloc=f"{credentials}{host}{port}"))

os.execv("/app/.venv/bin/python", ["/app/.venv/bin/python", "/app/run_api.py", "--host", "0.0.0.0", "--port", "8000"])
