from typing import Literal, TypedDict

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, ConfigDict, Field

from core.context_type import MemoryContext


class UserContent(BaseModel):
    """用户信息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str
    name: str = ""
    email: str = ""
    phone: str = ""
    department: str = ""
    title: str = ""
    roles: frozenset[str] = Field(default_factory=frozenset)
    active: bool = True


class UserToolResult(TypedDict):
    state: Literal["success", "error"]
    data: dict[str, object] | None
    error: str


# 模拟数据源：key 为 user_id
_MOCK_USERS: dict[str, UserContent] = {
    "u-1001": UserContent(
        user_id="u-1001",
        name="张三",
        email="zhangsan@example.com",
        phone="13800000001",
        department="研发部",
        title="后端工程师",
        roles=frozenset({"developer", "viewer"}),
        active=True,
    ),
    "u-1002": UserContent(
        user_id="u-1002",
        name="李四",
        email="lisi@example.com",
        phone="13800000002",
        department="产品部",
        title="产品经理",
        roles=frozenset({"product", "viewer"}),
        active=True,
    ),
    "u-1003": UserContent(
        user_id="u-1003",
        name="王五",
        email="wangwu@example.com",
        phone="13800000003",
        department="运维部",
        title="SRE",
        roles=frozenset({"ops", "admin"}),
        active=False,
    ),
}


def _find_user(user_id: str) -> UserToolResult:
    if not user_id:
        return {"state": "error", "data": None, "error": "缺少用户 ID"}
    user = _MOCK_USERS.get(user_id)
    if user is None:
        return {"state": "error", "data": None, "error": "用户不存在"}
    # 返回 JSON 数据，避免框架把 Pydantic 对象转换成模型难以解析的 repr。
    return {"state": "success", "data": user.model_dump(mode="json"), "error": ""}


@tool
async def get_user_info_by_user_id(user_id: str) -> UserToolResult:
    """根据已知用户 ID 查询模拟用户资料，不用于推测当前登录身份。

    返回字段：
        state: success 表示查到用户；error 表示查询失败。
        data: 成功时为用户资料；失败时为 null。
        error: 失败原因；成功时为空字符串。

    用户资料（data）：
        user_id: 用户唯一标识。
        name: 姓名。
        email: 邮箱。
        phone: 手机号。
        department: 部门。
        title: 职务。
        roles: 用户资料中的角色列表。
        active: 账号是否启用。

    结果处理：
        空字符串表示资料未提供，不代表用户不存在。
        active=false 表示账号停用，用户记录仍存在。
        state=error 时说明 error 中的原因，不编造用户资料。
    """
    return _find_user(user_id)


@tool
async def get_current_user_info(
    runtime: ToolRuntime[MemoryContext],
) -> UserToolResult:
    """查询当前登录用户的模拟资料；身份由运行时提供，无需用户输入 ID。

    返回字段：
        state: success 表示查到用户；error 表示查询失败。
        data: 成功时为用户资料；失败时为 null。
        error: 失败原因；成功时为空字符串。

    用户资料（data）：
        user_id: 用户唯一标识。
        name: 姓名。
        email: 邮箱。
        phone: 手机号。
        department: 部门。
        title: 职务。
        roles: 用户资料中的角色列表。
        active: 账号是否启用。

    结果处理：
        空字符串表示资料未提供，不代表用户不存在。
        active=false 表示账号停用，用户记录仍存在。
        state=error 时说明 error 中的原因，不编造用户资料。
    """
    if runtime.context is None:
        return {"state": "error", "data": None, "error": "缺少当前用户上下文"}
    return _find_user(runtime.context.user_id)


get_current_user_info.metadata = {"approval_mode": "read_only"}

__all__ = ["get_current_user_info", "get_user_info_by_user_id"]
