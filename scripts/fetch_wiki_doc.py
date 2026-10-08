"""Demo: 通过 tool 层从 Wiki 节点拉取 Docx 文档内容（基于 lark-cli）。

用法::

    # 1. 一次性飞书鉴权（已登录则跳过）
    lark-cli auth login

    # 2. 配置 .env
    cp .env.example .env
    # 编辑 .env 填入真实 LLM_API_KEY

    # 3. 跑脚本
    uv run python scripts/fetch_wiki_doc.py wikdXXXXXXXX

输出：Markdown 文本到 stdout。
"""

from __future__ import annotations

import argparse
import sys

from core.config import load_app_config
from core.utils.logging import configure_logging, get_logger
from feishu import (
    FeishuAPIError,
    LarkCli,
    fetch_feishu_doc,
    fetch_wiki_doc,
    resolve_wiki_node,
    set_default_client,
)
from feishu.exceptions import AstraAgentError

logger = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从飞书 Wiki 节点拉取 Docx 内容并打印为 Markdown。",
    )
    parser.add_argument(
        "node_token",
        help="Wiki 节点 token（URL /wiki/ 后的那串，如 wikdABC123xyz）。",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    configure_logging(level=args.log_level, fmt="console")

    try:
        cfg = load_app_config()
    except AstraAgentError as exc:
        logger.error("config.load.failed", error=str(exc))
        print(f"配置失败：{exc}", file=sys.stderr)
        return 2

    # 构造 LarkCli 并注入到 tools 层
    cli = LarkCli(
        identity=cfg.feishu.identity,
        binary=cfg.feishu.binary_path,
        timeout_seconds=cfg.feishu.timeout_seconds,
    )
    set_default_client(cli)

    try:
        info = resolve_wiki_node.invoke({"node_token": args.node_token})
    except FeishuAPIError as exc:
        logger.error("wiki.node.failed", error=str(exc))
        print(f"解析 Wiki 节点失败：{exc}", file=sys.stderr)
        return 3

    if info["obj_type"] != "docx":
        print(
            f"Wiki 节点指向 {info['obj_type']}，暂不支持（仅 docx）。",
            file=sys.stderr,
        )
        return 4

    try:
        markdown = fetch_feishu_doc.invoke({"document_id": info["obj_token"]})
    except FeishuAPIError as exc:
        logger.error("doc.fetch.failed", error=str(exc))
        print(f"拉取文档失败：{exc}", file=sys.stderr)
        return 5

    print(f"<!-- Wiki: {info['title']} (node_token={info['node_token']}) -->")
    print(f"<!-- Docx : {info['obj_token']} -->\n")
    print(markdown)
    _ = fetch_wiki_doc
    return 0


if __name__ == "__main__":
    sys.exit(main())