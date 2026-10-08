"""企业业务接入层。

`business` 下**每个子包 = 一个业务系统**（ERP / CRM / OA …），互不影响。
新增业务只需新建子包并在其 ``__init__.py`` 导出 ``TOOLS`` / ``SUBAGENTS``，
本文件会自动发现 —— 完整契约与目录约定见 `docs/design/business-plugins.md`。

两个容易踩的点：子包导入失败会被**跳过**（单业务挂掉不拖垮 agent），
但工具名 / sub-agent 名冲突会**直接抛错**（那是真 bug）。
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from deepagents.middleware.subagents import SubAgent
    from langchain_core.tools import BaseTool

logger = get_logger(__name__)

__all__ = [
    "BusinessBundle",
    "discover_business",
    "iter_business_package_names",
]


@dataclass(frozen=True)
class BusinessBundle:
    """一个业务子包的聚合结果。"""

    name: str
    tools: tuple[BaseTool, ...] = ()
    subagents: tuple[SubAgent, ...] = ()
    close: Callable[[], Awaitable[None]] | None = None


@dataclass
class _Discovery:
    """发现过程的可变累加器。"""

    bundles: list[BusinessBundle] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def iter_business_package_names() -> list[str]:
    """列出 :mod:`business` 下的所有业务子包名（已排序）。"""
    return sorted(
        info.name
        for info in pkgutil.iter_modules(__path__)
        if info.ispkg and not info.name.startswith("_")
    )


def _load_one(name: str) -> BusinessBundle:
    """导入单个业务子包并取出其契约成员。"""
    module = importlib.import_module(f"{__name__}.{name}")

    tools = tuple(getattr(module, "TOOLS", ()))
    subagents = tuple(getattr(module, "SUBAGENTS", ()))
    for agent in subagents:
        if not isinstance(agent, dict) or any(
            not isinstance(agent.get(key), str) or not agent[key].strip()
            for key in ("name", "description")
        ):
            raise TypeError(f"业务子包 {name!r} 的子 Agent 需要原生字典及非空 name/description")
    close = getattr(module, "close", None)

    if close is not None and not callable(close):
        msg = f"业务子包 {name!r} 的 close 不可调用"
        raise TypeError(msg)

    return BusinessBundle(name=name, tools=tools, subagents=subagents, close=close)


def _assert_no_conflicts(bundles: Sequence[BusinessBundle]) -> None:
    """同名工具 / sub-agent 视为业务边界破损，直接抛错。"""
    seen_tools: dict[str, str] = {}
    seen_agents: dict[str, str] = {}

    for bundle in bundles:
        for t in bundle.tools:
            owner = seen_tools.get(t.name)
            if owner is not None:
                msg = f"工具名 {t.name!r} 在业务 {owner!r} 与 {bundle.name!r} 中重复"
                raise ValueError(msg)
            seen_tools[t.name] = bundle.name

        for s in bundle.subagents:
            owner = seen_agents.get(s["name"])
            if owner is not None:
                msg = f"sub-agent 名 {s['name']!r} 在业务 {owner!r} 与 {bundle.name!r} 中重复"
                raise ValueError(msg)
            seen_agents[s["name"]] = bundle.name


def discover_business() -> _Discovery:
    """自动发现并导入全部业务子包。

    单个子包导入失败会被记录到 :attr:`_Discovery.errors` 并跳过，不影响其他业务。
    工具名 / sub-agent 名冲突则抛出 :class:`ValueError`（属于真 bug，不容忍）。

    Returns:
        :class:`_Discovery`，含 ``bundles``（按包名排序）与 ``errors``。
    """
    result = _Discovery()

    for name in iter_business_package_names():
        try:
            result.bundles.append(_load_one(name))
        except Exception as exc:
            logger.error("business.discover.failed", business=name, error=str(exc))
            result.errors[name] = str(exc)

    if result.errors:
        logger.warning(
            "business.discover.partial",
            failed=sorted(result.errors),
            ok=[b.name for b in result.bundles],
        )

    _assert_no_conflicts(result.bundles)

    logger.info(
        "business.discover.ok",
        businesses=[b.name for b in result.bundles],
        tools=[t.name for b in result.bundles for t in b.tools],
        subagents=[s["name"] for b in result.bundles for s in b.subagents],
    )
    return result


def collect_tools(bundles: Sequence[BusinessBundle]) -> tuple[BaseTool, ...]:
    """把所有业务的工具拍平成一个元组（保持发现顺序）。"""
    return tuple(t for b in bundles for t in b.tools)


def collect_subagents(bundles: Sequence[BusinessBundle]) -> tuple[SubAgent, ...]:
    """把所有业务的 sub-agent 拍平成一个元组（保持发现顺序）。"""
    return tuple(s for b in bundles for s in b.subagents)


def collect_closers(bundles: Sequence[BusinessBundle]) -> tuple[Callable[[], Awaitable[None]], ...]:
    """收集所有业务子包的可选 ``close()``。"""
    return tuple(b.close for b in bundles if b.close is not None)
