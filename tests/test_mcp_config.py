"""MCP 配置层测试（纯逻辑，不连服务）。"""

from __future__ import annotations

import json

import pytest

from core.mcp.config import (
    MCPConfigError,
    MCPServerConfig,
    load_mcp_config,
    parse_mcp_servers,
)


def test_parse_and_build_configs():
    configs = load_mcp_config(
        {
            "docs": {"transport": "http", "url": "https://mcp.example.com/mcp"},
            "fs": {
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "server-filesystem", "/data"],
            },
        }
    )
    assert [c.name for c in configs] == ["docs", "fs"]
    assert configs[0].problem() == ""
    assert configs[1].is_stdio
    assert configs[1].connection() == {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "server-filesystem", "/data"],
    }


def test_http_connection_carries_headers():
    cfg = MCPServerConfig(
        name="docs",
        transport="http",
        url="https://x/mcp",
        headers={"Authorization": "Bearer t"},
    )
    assert cfg.connection() == {
        "transport": "http",
        "url": "https://x/mcp",
        "headers": {"Authorization": "Bearer t"},
    }


def test_env_var_expansion(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCS_MCP_TOKEN", "s3cr3t")
    configs = load_mcp_config(
        {
            "docs": {
                "transport": "http",
                "url": "https://x/mcp",
                "headers": {"Authorization": "Bearer ${DOCS_MCP_TOKEN}"},
            }
        }
    )
    assert configs[0].headers["Authorization"] == "Bearer s3cr3t"


def test_env_var_default_value(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    configs = load_mcp_config(
        {
            "docs": {
                "transport": "http",
                "url": "${MISSING_VAR:-https://fallback/mcp}",
            }
        }
    )
    assert configs[0].url == "https://fallback/mcp"


def test_missing_env_var_is_an_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NOT_SET_ANYWHERE", raising=False)
    with pytest.raises(MCPConfigError, match="NOT_SET_ANYWHERE"):
        load_mcp_config(
            {
                "docs": {
                    "transport": "http",
                    "url": "https://x/mcp",
                    "env": {"T": "${NOT_SET_ANYWHERE}"},
                }
            }
        )


def test_bad_json_is_reported():
    with pytest.raises(MCPConfigError, match="不是合法 JSON"):
        parse_mcp_servers("{不是 json")


def test_unknown_key_is_rejected():
    with pytest.raises(MCPConfigError, match="配置不合法"):
        load_mcp_config({"docs": {"transport": "http", "url": "https://x", "headerss": {}}})


def test_missing_required_field_is_reported_by_problem():
    assert "command" in MCPServerConfig(name="a", transport="stdio").problem()
    assert "url" in MCPServerConfig(name="b", transport="http").problem()
    assert MCPServerConfig(name="c", transport="http", url="https://x").problem() == ""


def test_tool_allow_and_deny_lists():
    cfg = MCPServerConfig(
        name="docs",
        transport="http",
        url="https://x",
        include_tools=("search", "read"),
        exclude_tools=("read",),
    )
    assert cfg.allows("search")
    assert not cfg.allows("read")  # 黑名单优先
    assert not cfg.allows("delete")  # 不在白名单

    open_cfg = MCPServerConfig(name="open", transport="http", url="https://x")
    assert open_cfg.allows("anything")


def test_disabled_server_is_parsed_but_flagged():
    configs = load_mcp_config({"docs": {"transport": "http", "url": "https://x", "enabled": False}})
    assert configs[0].enabled is False


def test_no_config_returns_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MCP_SERVERS", raising=False)
    monkeypatch.delenv("MCP_CONFIG_FILE", raising=False)
    assert load_mcp_config() == []


def test_load_from_file(monkeypatch: pytest.MonkeyPatch, tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"docs": {"transport": "http", "url": "https://x/mcp"}}),
        encoding="utf-8",
    )
    monkeypatch.delenv("MCP_SERVERS", raising=False)
    monkeypatch.setenv("MCP_CONFIG_FILE", str(path))
    configs = load_mcp_config()
    assert [c.name for c in configs] == ["docs"]


def test_inline_env_wins_over_file(monkeypatch: pytest.MonkeyPatch, tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"from_file": {"transport": "http", "url": "https://f"}}), encoding="utf-8"
    )
    monkeypatch.setenv("MCP_CONFIG_FILE", str(path))
    monkeypatch.setenv(
        "MCP_SERVERS", json.dumps({"from_env": {"transport": "http", "url": "https://e"}})
    )
    assert [c.name for c in load_mcp_config()] == ["from_env"]


def test_missing_config_file_is_reported(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MCP_SERVERS", raising=False)
    monkeypatch.setenv("MCP_CONFIG_FILE", "C:/definitely/not/here/mcp.json")
    with pytest.raises(MCPConfigError, match="读取失败"):
        load_mcp_config()


def test_permission_defaults_are_permissive_but_explicit():
    cfg = MCPServerConfig(name="docs", transport="http", url="https://x")
    assert cfg.allow_roles == ()  # 空 = 不限角色
    assert cfg.forward_identity is False
    assert cfg.emit_events is True
    assert cfg.call_timeout_seconds == 60.0


def test_unknown_role_is_rejected_at_load_time():
    # 角色名写错会静默拒绝所有人 —— 必须在配置阶段就报出来
    with pytest.raises(MCPConfigError, match="未知角色"):
        load_mcp_config(
            {"docs": {"transport": "http", "url": "https://x", "allow_roles": ["editer"]}}
        )


def test_known_roles_and_policy_fields_are_accepted():
    configs = load_mcp_config(
        {
            "docs": {
                "transport": "http",
                "url": "https://x",
                "allow_roles": ["operator", "admin"],
                "forward_identity": True,
                "call_timeout_seconds": 5,
            }
        }
    )
    assert configs[0].allow_roles == ("operator", "admin")
    assert configs[0].forward_identity is True
    assert configs[0].call_timeout_seconds == 5
