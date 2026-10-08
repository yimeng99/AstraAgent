"""沙箱配置的环境变量读取。

回归背景：``SANDBOX_MAX_SANDBOXES`` 曾被写成 ``SANDBOX_MAX_SANDBBOXES``
（多一个 B）。环境变量名拼错不会报错，只会**静默回落到默认值**，用户配的
并发上限根本不生效 —— 所以这里锁住变量名。
"""

from __future__ import annotations

import pytest

from core.sandbox.config import load_sandbox_config


def test_max_sandboxes_reads_the_real_env_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SANDBOX_MAX_SANDBOXES", "9")
    assert load_sandbox_config().max_sandboxes == 9


def test_max_sandboxes_falls_back_to_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SANDBOX_MAX_SANDBOXES", raising=False)
    assert load_sandbox_config().max_sandboxes == 4


def test_typo_variable_is_ignored(monkeypatch: pytest.MonkeyPatch):
    """写错的那个名字不该被读（否则又会掩盖拼写问题）。"""
    monkeypatch.delenv("SANDBOX_MAX_SANDBOXES", raising=False)
    monkeypatch.setenv("SANDBOX_MAX_SANDBBOXES", "9")
    assert load_sandbox_config().max_sandboxes == 4


def test_other_knobs_are_read(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SANDBOX_BASE_URL", "http://sandbox:8080")
    monkeypatch.setenv("SANDBOX_IDLE_TTL_SECONDS", "120")
    monkeypatch.setenv("SANDBOX_IMAGE", "python:3.12-slim")
    cfg = load_sandbox_config()
    assert cfg.enabled
    assert cfg.idle_ttl_seconds == 120
    assert cfg.image == "python:3.12-slim"


def test_proxy_setting_reaches_sdk(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SANDBOX_BASE_URL", "http://sandbox:18080")
    monkeypatch.setenv("SANDBOX_USE_SERVER_PROXY", "true")
    assert load_sandbox_config().connection_config().use_server_proxy is True


def test_invalid_proxy_setting_is_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SANDBOX_USE_SERVER_PROXY", "treu")
    with pytest.raises(ValueError, match="SANDBOX_USE_SERVER_PROXY"):
        load_sandbox_config()
