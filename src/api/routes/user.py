"""用于前端联调的模拟用户接口。"""

from fastapi import APIRouter

from api.responses import ApiResult, success

router = APIRouter()

MOCK_USERS = [
    {
        "user_id": "u-1001",
        "name": "张三",
        "email": "zhangsan@example.com",
        "phone": "13800000001",
        "department": "研发部",
        "title": "后端工程师",
        "roles": ["developer", "viewer"],
        "active": True,
    },
    {
        "user_id": "u-1002",
        "name": "李四",
        "email": "lisi@example.com",
        "phone": "13800000002",
        "department": "产品部",
        "title": "产品经理",
        "roles": ["product", "viewer"],
        "active": True,
    },
    {
        "user_id": "u-1003",
        "name": "王五",
        "email": "wangwu@example.com",
        "phone": "13800000003",
        "department": "运维部",
        "title": "SRE",
        "roles": ["ops", "admin"],
        "active": False,
    },
]


@router.get("/user/getMockUserList", response_model=ApiResult[list[dict[str, object]]])
async def get_mock_user_list():
    return success(MOCK_USERS)
