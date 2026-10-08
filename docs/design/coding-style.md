# Coding Style — 语法与命名规范

> 适用范围：本项目所有 `src/` 下的 Python 源码。
> 主要参考：[PEP 8](https://peps.python.org/pep-0008/)、[PEP 257](https://peps.python.org/pep-0257/)、[PEP 484](https://peps.python.org/pep-0484/)、[Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)。

---

## 1. 行长与缩进

| 项 | 规则 |
|----|------|
| 缩进 | **4 空格**（PEP 8） |
| 制表符 | **禁止** |
| 行长 | **100 字符**（软上限）。超长时优先断行，不要硬拼。Docstring/注释 72 |
| 文件结尾 | **1 个空行** |
| 续行 | 优先**垂直对齐括号**或**悬挂缩进**（多 4 空格） |

```python
# 好的续行：垂直对齐
foo = long_function_name(var_one, var_two,
                         var_three, var_four)

# 悬挂缩进（多 4 空格）
result = some_call(
    first_arg,
    second_arg,
    third_arg,
)
```

---

## 2. 命名规范

| 类型 | 风格 | 示例 |
|------|------|------|
| **模块（文件名）** | `snake_case`，全小写、单词间下划线 | `agent_runner.py`、`feishu_doc.py` |
| **包（目录名）** | `snake_case`，全小写、避免下划线（短） | `agent/`、`tools/`、`memory/` |
| **类** | `PascalCase`（CapWords） | `class AgentRunner:`、`class FeishuClient:` |
| **异常** | `PascalCase` + `Error` 后缀 | `class ConfigError(Exception):` |
| **函数 / 变量** | `snake_case` | `def fetch_doc(...):`、`session_id = "..."` |
| **方法** | `snake_case` | `def run(self):`、`def _validate(self):` |
| **常量** | `UPPER_SNAKE_CASE` | `MAX_RETRIES = 3`、`DEFAULT_TIMEOUT = 30` |
| **私有属性/函数** | 单下划线前缀 | `_internal_state`、`_parse_response()` |
| **强私有（避免子类覆盖）** | 双下划线前缀（name-mangling） | `__strict_private`（**慎用**） |
| **魔术方法 / dunder** | `__name__` 形式 | `__init__`、`__repr__`、`__all__` |
| **类型变量** | `PascalCase` + 后缀 | `UserT`、`RequestT`、`AnyStr` |
| **布尔变量/方法** | `is_/has_/can_/should_` 前缀 | `is_active`、`can_write` |

### 避免

- 单字符名（除循环计数器 `i, j`、异常 `e`、文件句柄 `f`）
- 缩写（除常用 `id, url, api, db, ok, err`）
- `-`（连字符）出现在模块名 —— **不可作为 Python 标识符**
- 中文 / emoji 出现在标识符中
- 名字里携带类型（`user_list` → `users`）

---

## 3. Import 顺序

按以下分组，**每组之间空一行**：

```python
# 1. __future__ imports（按字母）
from __future__ import annotations

# 2. 标准库
import asyncio
import logging
from pathlib import Path

# 3. 第三方库
from langchain.tools import tool
from pydantic import BaseModel

# 4. 本项目内部（绝对导入，禁止相对）
from astra_agent.config import WORKSPACE_ROOT
from astra_agent.tools import fetch_feishu_doc
```

**强制规则：**

- 绝对导入（`from astra_agent.x import y`）**优于**相对导入（`from .x import y`）
- 禁止 `from x import *`
- 每行只导入一个；多对象可用 `from x import a, b, c`
- 顺序使用 `ruff` / `isort` 自动整理（profile `black`）

---

## 4. 类型提示（Type Hints）

> **数据模型与对象的完整规则**（Pydantic / dataclass / Enum / Protocol / ABC / 字段命名 / 序列化等）见 [`data-modeling.md`](./data-modeling.md)。本节仅讲**类型提示语法**。

### 4.1 基本风格

- Python ≥ 3.10（本项目 ≥ 3.13），**统一使用 PEP 604 语法**：`int | str`，不再用 `Union[int, str]`
- 用 `X | None`，**不再用 `Optional[X]`**
- 用内置泛型 `list[int]`、`dict[str, int]`，**不再用 `List[int]`、`Dict[str, int]`**
- 所有函数签名必须带类型提示（公开 API 强制，内部辅助函数建议）
- 所有公开 API 必须返回类型，不允许只有参数没有返回类型

```python
# 推荐
def lookup_user(user_id: str) -> dict | None:
    ...

# 不推荐
from typing import Optional, Dict
def lookup_user(user_id: str) -> Optional[Dict]:
    ...
```

### 4.2 复杂签名

- 参数/返回类型差异大时使用 `@overload`：

```python
from typing import overload

@overload
def parse(value: str) -> dict: ...
@overload
def parse(value: bytes) -> dict: ...
def parse(value): ...
```

- 不要让签名随（关联外部数据时不要用「随便什么都接受」的 union）

---

## 5. Docstring（PEP 257 + Google 风格）

所有 **module / class / public function / public method** 必须有 docstring。

```python
def fetch_feishu_doc(document_id: str, *, timeout: float = 30.0) -> str:
    """拉取飞书文档纯文本内容。

    Args:
        document_id: 飞书文档 URL `/docx/` 后的标识。
        timeout: HTTP 请求超时（秒），默认 30。

    Returns:
        还原后的 Markdown 文本。

    Raises:
        RuntimeError: 飞书 API 返回非 success。
        TimeoutError: 请求超过 `timeout` 秒。

    Example:
        >>> text = fetch_feishu_doc("doccnABC123")
        >>> "# 标题" in text
        True
    """
```

### 风格选择

- **默认：Google 风格**（`Args:`、`Returns:`、`Raises:`、`Yields:`）
- 复杂数学 / NumPy 类库可用 **NumPy 风格**

---

## 6. 字符串与引号

- 默认 **双引号** `"`，三引号 `"""` 用于 docstring
- f-string 用于格式化；**不要** `.format()` 或 `%`
- 字符串内含双引号时用单引号，反之亦然

```python
name = "Astra"
greeting = f"Hello, {name}!"
```

---

## 7. 布尔与比较

- 始终用 `is` / `is not` 判断 `None`、`True`、`False`
- `if x:` 而非 `if x is True:`；`if not x:` 而非 `if x == False:`
- 序列空判断：`if not items:` 而非 `if len(items) == 0:`

---

## 8. 异常与错误处理

### 8.1 抛出

- 抛**具体**异常，不要裸 `raise Exception`
- 自定义异常继承项目根异常 `AstraAgentError`
- 异常链用 `raise NewError(...) from original`

```python
class AstraAgentError(Exception):
    """项目根异常。"""

class FeishuAPIError(AstraAgentError):
    """飞书 API 调用失败。"""

if not resp.success():
    raise FeishuAPIError(f"code={resp.code}, msg={resp.msg}") from None
```

### 8.2 捕获

- 捕获**具体**异常，不要裸 `except:` 或 `except Exception:`
- 重新抛出时保留堆栈（`raise` 而不是 `raise e`）
- 不要用异常做控制流

### 8.3 上下文管理

资源类对象用 `with`：文件、网络连接、锁。

### 8.4 内部契约与失败边界

- 外部请求、存储格式与 SDK 输入在各自边界处理；内部使用已经确定的类型和必填字段。
- 不用 `getattr` / `hasattr` / 连续 `.get(..., {})` 兼容本项目没有支持的对象形态。
- 预期工具输入错误用 `ToolException`；编程错误继续抛出，不能伪装成可恢复工具结果。
- 仅请求执行边界、资源清理边界和明确可选集成可统一捕获异常，必须说明处理目的并保留日志；不在每层重复兜底。
- 新增状态应说明唯一维护者；不要从展示文案或工具数量猜测执行状态。

---

## 9. 日志

- **永远不要** 用 `print()` 调试；用 `logging` 或 `structlog`
- 模块级 logger：`logger = logging.getLogger(__name__)`
- 懒格式化（占位符而非拼接）：

```python
logger.info("User %s fetched doc %s in %.2fs", user_id, doc_id, elapsed)
# 不要：
logger.info(f"User {user_id} fetched doc {doc_id} in {elapsed:.2f}s")
```

- 生产环境建议 **JSON 结构化**：`structlog` 或 `logging` + `python-json-logger`
- 异常信息用 `logger.exception(...)` 或 `exc_info=True`

```python
import structlog
logger = structlog.get_logger(__name__)

logger.info("doc.fetched", doc_id=doc_id, elapsed_ms=elapsed)
logger.exception("doc.fetch.failed", doc_id=doc_id)
```

---

## 10. 异步代码（asyncio）

- 所有 I/O 函数 `async def`，命名加 `async_` 前缀或保留动词原形（按调用点上下文）
- 不要在同步函数里 `asyncio.run` —— 提到入口
- `await` 的对象必须支持 `__await__`；CPU 密集放 `asyncio.to_thread`
- 取消语义：`try/except CancelledError` 后清理资源

---

## 11. 代码组织

- 每个文件 < **500 行**；超出要拆分
- 模块顶部顺序：
  1. `"""docstring"""`
  2. `from __future__ import annotations`（如需）
  3. `__all__ = [...]`（明确公开 API）
  4. import
  5. 模块级常量
  6. 模块级 logger
  7. 函数 / 类
- 类成员顺序：dunder → public → protected（`_`） → private（`__`）

---

## 12. 工具强制

| 工具 | 用途 | 命令 |
|------|------|------|
| `ruff check` | Lint（替代 flake8/isort/pyupgrade） | `uv run ruff check src tests` |
| `ruff format` | 格式化（替代 black） | `uv run ruff format src tests` |
| `mypy` | 类型检查（严格模式） | `uv run mypy src` |
| `pytest` | 测试 + 覆盖率 | `uv run pytest --cov=astra_agent` |

> 提交前必须 `ruff check src tests && ruff format --check src tests && mypy src` 全绿。

---

## 13. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-09-24 | 初版：基于 PEP 8/257/484/604、Google Style、2025 现代实践整合 |
