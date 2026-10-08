"""在图的硬步数限制之前留出最终答复的空间。"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.agents.middleware.types import ModelRequest, ModelResponse, PrivateStateAttr
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.managed.is_last_step import RemainingStepsManager
from langgraph.runtime import Runtime


class BudgetState(AgentState):
    # Managed value 每次执行重新计算，不写入 checkpoint，也不跨用户共享计数。
    # LangGraph 只识别最后一个 Annotated 元数据作为 managed value。
    remaining_steps: Annotated[int, PrivateStateAttr, RemainingStepsManager]
    budget_final: Annotated[bool, PrivateStateAttr]


_FINAL_INSTRUCTION = """
本轮执行即将达到步数限制。这次必须直接给出最终答复，不再调用任何工具或派发子任务。
根据已有工具结果总结已完成的工作，列出已生成文件的位置和仍未完成的工作。
明确说明本轮已到执行预算，需要用户继续才能完成剩余工作；不得宣称未完成任务已完成，
不得编造文件或下载链接。子任务应将现有结果及未完成事项交还主 Agent。
"""
_NOTICE = "本轮接近执行步数上限，已停止新增操作。请继续任务以完成剩余工作。"


class ExecutionBudgetMiddleware(AgentMiddleware[BudgetState]):
    state_schema = BudgetState

    def __init__(self, reserve_steps: int = 12) -> None:
        # 一个模型/工具循环还包含审批、文件上下文等图节点，不能只留一两步。
        self.reserve_steps = reserve_steps

    def before_model(self, state: BudgetState, runtime: Runtime) -> dict:
        # model 节点不接收 managed channel；在显式 state schema 的钩子中读取。
        return {"budget_final": state["remaining_steps"] <= self.reserve_steps}

    async def abefore_model(self, state: BudgetState, runtime: Runtime) -> dict:
        return self.before_model(state, runtime)

    def _request(self, request: ModelRequest) -> ModelRequest:
        if not request.state["budget_final"]:
            return request
        blocks = list(request.system_message.content_blocks) if request.system_message else []
        blocks.append({"type": "text", "text": _FINAL_INSTRUCTION})
        return request.override(
            tools=[], tool_choice=None, system_message=SystemMessage(content=blocks)
        )

    @staticmethod
    def _response(response: ModelResponse[Any], final: bool) -> ModelResponse[Any]:
        if not final:
            return response
        # 不遵守禁用工具的 provider 也不能再启动操作；仅处理本次的新响应。
        messages = []
        for message in response.result:
            if isinstance(message, AIMessage) and message.tool_calls:
                message = message.model_copy(
                    update={
                        "content": f"{message.text}\n\n{_NOTICE}".strip(),
                        "tool_calls": [],
                        "invalid_tool_calls": [],
                        "additional_kwargs": {},
                    }
                )
            messages.append(message)
        return ModelResponse(result=messages, structured_response=response.structured_response)

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        adjusted = self._request(request)
        return self._response(handler(adjusted), adjusted is not request)

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        adjusted = self._request(request)
        return self._response(await handler(adjusted), adjusted is not request)
