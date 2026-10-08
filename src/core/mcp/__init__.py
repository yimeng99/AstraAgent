"""MCP（Model Context Protocol）接入层。

三个子模块（调用方按需直连）：

* :mod:`core.mcp.config` —— 服务配置（``MCP_SERVERS`` / ``MCP_CONFIG_FILE``）；
* :mod:`core.mcp.registry` —— 长会话生命周期、工具注册、失败隔离、自检状态；
* :mod:`core.mcp.interceptors` —— 角色校验、身份透传、调用超时与日志。

生命周期挂在 :func:`core.agent.core_lifespan` 上；连通性自检跑
``python -m core.mcp``。
"""

__all__: list[str] = []
