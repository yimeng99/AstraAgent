"""LangChain 消息内容的文本提取。

两个调用点：流式解析（从 LLM chunk 取增量文本）与历史回显（把存下来的
content 压成纯文本）。原先各写一份，多模态块的判断容易各自漂移。
"""

from __future__ import annotations

__all__ = ["text_from_chunk", "text_of", "tool_result_failed", "tool_result_text"]


def tool_result_failed(output: object, name: str = "") -> bool:
    """实时事件和历史回放使用相同判定；兼容旧 Python 工具的 Markdown 结果。"""
    import json
    import re

    status = output.get("status") if isinstance(output, dict) else getattr(output, "status", None)
    if status == "error":
        return True
    content = (
        output.get("content", output)
        if isinstance(output, dict)
        else getattr(output, "content", output)
    )
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (ValueError, TypeError):
            if name in {"render_document", "render_document_from_files", "render_spreadsheet"}:
                return content.startswith(
                    (
                        "sections 不能为空",
                        "sheets 不能为空",
                        "文件名必须",
                        "文件路径不合法",
                        "读取章节文件失败",
                        "生成文档失败",
                        "生成 Excel 失败",
                        "文件已渲染但保存失败",
                        "章节数超过",
                        "sections 与 source_files",
                    )
                )
            if name == "run_python":
                match = re.match(r"\*\*退出码\*\*：(-?\d+)", content)
                if match:
                    return int(match[1]) != 0
            if name == "get_sandbox_environment":
                # 旧检查点曾把失败保存为普通文本，历史回放也不能显示成功。
                return content.startswith(
                    (
                        "沙箱环境查询失败",
                        "沙箱环境查询超时",
                        "代码执行沙箱暂不可用",
                        "无法识别调用者身份",
                        "当前账号没有使用沙箱的权限",
                    )
                )
            return False
    return isinstance(content, dict) and content.get("state") == "error"


def tool_result_text(output: object) -> str:
    """工具结果可能是 ToolMessage 或字典；只把有限的可读文本交给浏览器。"""
    import json

    content = getattr(output, "content", output)
    if isinstance(content, (dict, tuple)):
        result = json.dumps(content, ensure_ascii=False, default=str)
    else:
        result = text_of(content)
    limit = 20_000
    return result[:limit] + ("\n…结果过长，已截断" if len(result) > limit else "")


def text_of(content: object) -> str:
    """把 content（``str`` 或多模态块数组）压成纯文本。

    多模态块里只取 ``type == "text"`` 的部分，跳过 image 等二进制内容。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_text_of_block(block) for block in content)
    return "" if content is None else str(content)


def text_from_chunk(chunk: object) -> str:
    """从 LLM chunk（``AIMessageChunk`` 或 dict）提取文本。"""
    if isinstance(chunk, dict):
        return text_of(chunk.get("content"))
    return text_of(getattr(chunk, "content", None))


def _text_of_block(block: object) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict) and block.get("type") == "text":
        return str(block.get("text", ""))
    return ""
