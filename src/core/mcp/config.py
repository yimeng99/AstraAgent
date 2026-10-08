"""MCP 服务配置 —— 从 ``MCP_SERVERS``（一行 JSON，优先）或 ``MCP_CONFIG_FILE`` 加载。

和沙箱一样**全部可选**：没配就是"未接入 MCP"，上层照常对话；单个服务配错也只丢
它自己（记日志 + 跳过），不让应用起不来。值里支持 ``${VAR}`` / ``${VAR:-默认值}``
展开，所以 token 别写进仓库 —— 写 ``"Bearer ${DOCS_MCP_TOKEN}"`` 即可。
配置示例与字段说明见 `.env.example` 的 MCP 段。
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.context_type import ROLE_PERMISSIONS
from core.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = get_logger(__name__)

__all__ = [
    "HEADER_TRANSPORTS",
    "MCPConfigError",
    "MCPServerConfig",
    "load_mcp_config",
    "parse_mcp_servers",
]

#: 环境变量引用：``${VAR}`` 或带默认值的 ``${VAR:-默认}``
_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

#: 支持自定义请求头的传输（stdio 是本地子进程，没有 header 这回事）
HEADER_TRANSPORTS: frozenset[str] = frozenset({"http", "streamable_http", "sse"})


class MCPConfigError(RuntimeError):
    """MCP 配置本身不合法（JSON 语法错、变量缺失等）。"""


class MCPServerConfig(BaseModel):
    """单个 MCP 服务的连接配置（字段清单见 `.env.example` 的 MCP 段）。

    三个不那么显然的点：``name`` 会进工具名前缀（``mcp__{name}__{tool}``，
    建议只用字母数字下划线）；``headers`` 是 HTTP/SSE 传输的鉴权与 trace 入口；
    ``allow_roles`` 为空表示不限制角色。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    transport: Literal["stdio", "http", "streamable_http", "sse"] = "http"
    enabled: bool = True

    # ── stdio ──────────────────────────────────────────────
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = ""

    # ── http / sse ─────────────────────────────────────────
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)

    # ── 工具过滤 ────────────────────────────────────────────
    include_tools: tuple[str, ...] = ()
    exclude_tools: tuple[str, ...] = ()

    # ── 权限 / 身份 ─────────────────────────────────────────
    #: 允许调用该服务的角色（空 = 不限制）。取值见 core.context_type.ROLE_PERMISSIONS。
    allow_roles: tuple[str, ...] = ()
    #: 是否把调用者身份透传给 MCP 服务（HTTP/SSE 传输会带 X-User-Id 等头）。
    #: 打开后由下游服务自己做行级权限判定 —— 比我们这边猜权限更准。
    forward_identity: bool = False
    #: 单次调用超时。慢服务不能拖死一整轮对话。
    call_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    #: 调用时是否推 tool.start / tool.end（前端显示"正在查询外部资料…"）。
    emit_events: bool = True

    connect_timeout_seconds: float = Field(default=15.0, gt=0, le=300)

    @field_validator("allow_roles")
    @classmethod
    def _check_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """角色名写错会**静默拒绝所有人**，所以这里直接报错。"""
        unknown = [role for role in value if role not in ROLE_PERMISSIONS]
        if unknown:
            known = "、".join(sorted(ROLE_PERMISSIONS))
            raise ValueError(f"未知角色 {unknown}，可用角色：{known}")
        return value

    @property
    def is_stdio(self) -> bool:
        """是否走本地子进程。"""
        return self.transport == "stdio"

    def problem(self) -> str:
        """配置是否可用；返回空串表示可用，否则返回给日志看的原因。"""
        if self.is_stdio:
            if not self.command.strip():
                return "stdio 传输必须提供 command"
        elif not self.url.strip():
            return f"{self.transport} 传输必须提供 url"
        return ""

    def allows(self, tool_name: str) -> bool:
        """该工具是否在允许范围内（白名单优先，再排队黑名单）。"""
        if self.include_tools and tool_name not in self.include_tools:
            return False
        return tool_name not in self.exclude_tools

    def connection(self) -> dict[str, Any]:
        """转成 ``MultiServerMCPClient`` 认识的连接字典。"""
        if self.is_stdio:
            connection: dict[str, Any] = {
                "transport": "stdio",
                "command": self.command,
                "args": list(self.args),
            }
            if self.env:
                connection["env"] = dict(self.env)
            if self.cwd:
                connection["cwd"] = self.cwd
            return connection

        connection = {"transport": self.transport, "url": self.url}
        if self.headers:
            connection["headers"] = dict(self.headers)
        return connection


def load_mcp_config(raw: Mapping[str, Any] | None = None) -> list[MCPServerConfig]:
    """读取 MCP 服务配置（`raw` 用于测试注入；未配置时返回空列表）。

    Raises:
        MCPConfigError: ``MCP_SERVERS`` 不是合法 JSON、配置文件读不到，
            或某个服务的配置不合法。
    """
    if raw is None:
        raw = _read_raw()
    if not raw:
        return []

    if not isinstance(raw, dict):
        raise MCPConfigError("MCP 配置必须是以服务名为 key 的 JSON 对象")

    configs: list[MCPServerConfig] = []
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise MCPConfigError(f"服务 {name!r} 的配置必须是 JSON 对象")
        payload = _expand(spec, path=name)
        # 允许配置里写 name 覆盖 key，但以 key 为准更不容易错
        payload.pop("name", None)
        try:
            configs.append(MCPServerConfig(name=name, **payload))
        except ValidationError as exc:
            raise MCPConfigError(f"服务 {name!r} 配置不合法：{exc}") from exc

    logger.info(
        "mcp.config.loaded",
        servers=[c.name for c in configs],
        enabled=[c.name for c in configs if c.enabled],
    )
    return configs


def parse_mcp_servers(text: str, *, source: str = "MCP_SERVERS") -> dict[str, Any]:
    """把一段 JSON 文本解析成配置字典（``load_mcp_config`` 的字符串入口）。"""
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        data = json.loads(stripped)
    except ValueError as exc:
        raise MCPConfigError(f"{source} 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise MCPConfigError(f"{source} 必须是以服务名为 key 的 JSON 对象")
    return data


def _read_raw() -> dict[str, Any]:
    """按优先级取原始配置：``MCP_SERVERS`` > ``MCP_CONFIG_FILE``。"""
    inline = os.getenv("MCP_SERVERS", "")
    if inline.strip():
        return parse_mcp_servers(inline, source="MCP_SERVERS")

    path = os.getenv("MCP_CONFIG_FILE", "").strip()
    if not path:
        return {}

    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise MCPConfigError(f"MCP_CONFIG_FILE 读取失败（{path}）：{exc}") from exc
    return parse_mcp_servers(text, source=f"MCP_CONFIG_FILE({path})")


def _expand(value: Any, *, path: str) -> Any:
    """递归展开值里的 ``${VAR}``；缺失且无默认值时直接报错（别静默变成空串）。"""
    if isinstance(value, str):
        return _expand_str(value, path=path)
    if isinstance(value, list):
        return [_expand(item, path=f"{path}[]") for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, path=f"{path}.{key}") for key, item in value.items()}
    return value


def _expand_str(value: str, *, path: str) -> str:
    def replace(match: re.Match[str]) -> str:
        var, default = match.group(1), match.group(2)
        current = os.environ.get(var)
        if current is not None:
            return current
        if default is not None:
            return default
        raise MCPConfigError(f"{path} 引用了未设置的环境变量 ${{{var}}}")

    return _ENV_VAR_RE.sub(replace, value)
