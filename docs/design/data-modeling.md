# Data Modeling — 字段命名与对象编写规则

> 适用范围：`src/astra_agent/` 下所有数据类、模型、DTO、值对象、抽象类。
> 配套：[`coding-style.md`](./coding-style.md)（语法基础）、[`architecture.md`](./architecture.md)（依赖方向）。

---

## 1. 字段命名（Field Naming）

### 1.1 基本规则

| 类型 | 风格 | 示例 |
|------|------|------|
| **所有字段** | `snake_case` | `user_id`, `created_at`, `max_retries` |
| **bool 字段** | `is_/has_/can_/should_/needs_` 前缀 | `is_active`, `has_children`, `can_retry` |
| **集合字段** | 复数名词 | `users`, `tags`, `items` |
| **负数/正数含义** | 不用反义双关；用正向表达 | `enabled: bool` ✅；`disabled: bool` ❌ |

### 1.2 单位进名（强制）

字段名必须自带单位，**不依赖注释**：

| 字段类型 | 命名 | 错误命名 |
|---------|------|---------|
| 时间（秒） | `*_seconds`, `*_secs` | `timeout`, `delay` |
| 时间（毫秒） | `*_milliseconds`, `*_ms` | `elapsed` |
| 时间戳 | `*_at`（ISO 8601 字符串或 UTC datetime） | `time`, `ts`（过于模糊）|
| 字节 | `*_bytes` | `size`, `length` |
| 千字节 / 兆字节 | `*_kb`, `*_mb`, `*_gb` | — |
| 百分比 | `*_ratio`（0.0–1.0）或 `*_percent`（0–100） | `rate` |
| 计数 | `*_count` | `num`, `total`（单数）|
| 重试次数 | `*_attempts`, `*_retries` | `try_count` |
| 比率 / 概率 | `*_ratio`, `*_probability` | `rate` |

```python
# ✅ 好：单位自带
timeout_seconds: float = 30.0
elapsed_ms: int = 421
max_size_bytes: int = 10 * 1024 * 1024
retry_attempts: int = 3
cache_ttl_seconds: int = 3600

# ❌ 差：单位靠注释
timeout: float = 30.0  # 秒
elapsed: int = 421     # 毫秒
```

### 1.3 字段名禁忌

| 禁止 | 替代 | 原因 |
|------|------|------|
| `user_list`, `str_name`, `dict_data` | `users`, `name`, `data` | 类型进名是冗余信息 |
| `info`, `data`, `obj`, `tmp` | 具体业务名词 | 太泛，无信息量 |
| `id` 当字段名时无前缀 | 实体 id 用 `<entity>_id` | 多表 JOIN 时必须区分 |
| `date`, `time` | `created_at`, `expires_at` | 与 `datetime.date/time` 同名，IDE 提示混乱 |
| 中文 / emoji | 英文 | 不利于搜索、IDE、国际化 |

### 1.4 序列化别名（camelCase ↔ snake_case）

代码内字段一律 `snake_case`；对外（API、JSON、YAML）如需 `camelCase`，用 **Pydantic `alias`**：

```python
from pydantic import BaseModel, ConfigDict, Field


class FeishuDoc(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_id: str = Field(alias="documentId")
    created_at: str = Field(alias="createdAt")
    is_public: bool = Field(alias="isPublic", default=False)

# 内部访问
doc = FeishuDoc.model_validate({"documentId": "doccnABC", "createdAt": "2026-09-24"})
doc.document_id          # 'doccnABC'（内部代码用 snake_case）

# 对外序列化
doc.model_dump(by_alias=True)
# {'documentId': 'doccnABC', 'createdAt': '2026-09-24', 'isPublic': False}
```

---

## 2. 对象选型（选哪个）

| 场景 | 选择 | 理由 |
|------|------|------|
| 外部输入（API、YAML、ENV 用户配置） | **Pydantic v2 `BaseModel`** | 运行时校验、类型强转、Schema 生成 |
| 内部不可变 DTO / 值对象 | **`@dataclass(frozen=True, slots=True)`** | 零依赖、快、不可变 |
| 有限枚举集合 | **`enum.StrEnum`**（3.11+） | 类型安全、可序列化 |
| 行为抽象（duck typing） | **`typing.Protocol`** | 结构子类型，无需继承 |
| 强约束模板方法 | **`abc.ABC`** + `@abstractmethod` | 强制子类实现 |
| 简单结构化 dict 注释 | **`TypedDict`** | 替代裸 `dict[str, Any]` |
| 普通有状态服务类 | **普通类**（不继承 `object`） | 组合式服务对象 |

### 决策流程图

```
要定义一个新类型
  ├─ 是「数据」还是「行为」？
  │    ├─ 数据
  │    │    ├─ 来自外部 / 需要校验？
  │    │    │    ├─ 是 → Pydantic BaseModel
  │    │    │    └─ 否 → @dataclass(frozen=True, slots=True)
  │    │    └─ 是有限枚举？
  │    │         └─ 是 → StrEnum
  │    └─ 行为
  │         ├─ 多个不相关类要遵守同一接口？
  │         │    ├─ 是，且不强制继承 → Protocol
  │         │    └─ 是，且要强制实现 → abc.ABC
  │         └─ 否 → 普通类
```

---

## 3. Pydantic 编写规则

### 3.1 `model_config` 标准

```python
from pydantic import ConfigDict

class MyModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,                  # 不可变（值对象语义）
        extra="forbid",               # 多余字段报错（API 边界推荐）
        str_strip_whitespace=True,    # 自动去首尾空白
        str_to_lower=False,           # 默认不转小写（按需开启）
        use_enum_values=True,           # 序列化时输出枚举值
        populate_by_name=True,         # 同时接受 snake_case 与 alias
    )
```

| 子场景 | `extra` 设置 | 理由 |
|--------|------------|------|
| 外部 API 输入 | `"forbid"` | 多余字段说明客户端/接口变了 |
| 内部配置 | `"ignore"` | 容错 |
| 严格 schema | `"forbid"` | 跟 OpenAPI 对齐 |

### 3.2 字段定义

```python
from pydantic import BaseModel, Field

class FeishuConfig(BaseModel):
    """飞书应用配置。"""

    app_id: str = Field(
        description="飞书应用 App ID，cli_xxx 开头",
        examples=["cli_xxxxxxxxxxxxxxxx"],
        min_length=8,
    )
    app_secret: str = Field(
        description="飞书应用 App Secret",
        repr=False,                              # 不进 repr，避免日志泄露
    )
    timeout_seconds: float = Field(
        default=30.0,
        ge=0.1,
        le=300.0,
        description="HTTP 请求超时（秒）",
    )
    retry_attempts: int = Field(
        default=3,
        ge=0,
        le=10,
        description="失败重试次数",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="标签列表",
    )
```

**强制：**

- 每个字段必须 `description=`（生成 OpenAPI、JSON Schema）
- 字符串字段加 `min_length` / `max_length`
- 数值字段加 `ge` / `le`
- 集合字段默认 `default_factory=list` / `dict`，**不用** `[]` / `{}`（可变默认）
- 敏感字段 `repr=False`

### 3.3 不要做的事

| ❌ 禁止 | ✅ 替代 |
|---------|---------|
| 重写 `__init__` | 用 `field_validator` / `model_validator` |
| 在 `__init__` 里写业务逻辑 | 工厂方法 `Model.create(...)` 或 `model_validate` |
| 用 `.dict()` | `model_dump()` |
| 用 `.json()` | `model_dump_json()` |
| 把 ORM 对象直接当 Pydantic | 显式 `from_attributes=True` 或手写转换 |
| 用裸 `Any` | 用 `TypedDict` 或具体类型 |

### 3.4 校验器

```python
from pydantic import BaseModel, field_validator, model_validator

class DocumentRequest(BaseModel):
    document_id: str
    content: str

    @field_validator("document_id")
    @classmethod
    def _validate_doc_id(cls, v: str) -> str:
        if not v.startswith("doccn"):
            raise ValueError("document_id 必须以 'doccn' 开头")
        return v.lower()

    @model_validator(mode="after")
    def _check_pair(self) -> "DocumentRequest":
        if not self.document_id and not self.content:
            raise ValueError("document_id 与 content 至少提供一个")
        return self
```

### 3.5 计算字段

```python
from pydantic import BaseModel, computed_field

class Rectangle(BaseModel):
    width: float
    height: float

    @computed_field
    @property
    def area(self) -> float:
        return self.width * self.height
```

### 3.6 判别联合（Polymorphism）

```python
from typing import Annotated
from pydantic import BaseModel, Field
from typing import Literal

class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    content: str

class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    url: str

Block = Annotated[
    TextBlock | ImageBlock,
    Field(discriminator="type"),
]

class Document(BaseModel):
    title: str
    blocks: list[Block]   # 按 type 自动反序列化
```

---

## 5. dataclass 编写规则

### 5.1 标准三件套

```python
from dataclasses import dataclass, field

@dataclass(frozen=True, slots=True, kw_only=True)
class ToolResult:
    """不可变、可哈希的 tool 执行结果。"""

    name: str
    output: str
    elapsed_ms: float
    metadata: dict[str, str] = field(default_factory=dict)
```

| 参数 | 强制 | 理由 |
|------|------|------|
| `frozen=True` | ✅ | 不可变 → 可哈希 → 可作 dict key |
| `slots=True` | ✅ | 省内存、增访问速度、阻止新增属性 |
| `kw_only=True` | ✅ | 强制显式传名，避免位置参数顺序错位 |
| `eq=True`（默认） | ✅ | 自动生成 `__eq__` / `__repr__` |

### 5.2 字段规则

- **可变默认值**必须用 `field(default_factory=...)`：

```python
# ❌ 错：可变默认值（dataclass 会复制，但 list 仍指向同一对象）
items: list[str] = []

# ✅ 对
items: list[str] = field(default_factory=list)
```

- **不写** `__init__` / `__eq__` / `__repr__` —— dataclass 自动生成

### 5.3 继承约束

- 父类不要存字段，子类才存字段（避免 MRO 错位）
- 子类加 `kw_only=True`，与父类对齐
- 浅继承（≤2 层），深继承优先用组合

```python
@dataclass(frozen=True, slots=True)
class ToolResult:
    name: str
    elapsed_ms: float

@dataclass(frozen=True, slots=True)
class FeishuToolResult(ToolResult):
    document_id: str
    page_count: int
```

---

## 6. Enum / StrEnum 编写

### 6.1 优先 StrEnum

```python
from enum import StrEnum, auto

class LogLevel(StrEnum):
    DEBUG = auto()       # → 'DEBUG'
    INFO = auto()
    WARNING = auto()
    ERROR = auto()

# 可直接当 str 用
logger.setLevel(LogLevel.INFO)
print(LogLevel.INFO == "INFO")    # True
```

### 6.2 命名与值

- 成员名 `UPPER_SNAKE_CASE`
- 值用 `auto()`（除非需要外部系统特定值，如 HTTP status）
- 不要混合大小写 / 拼写不一致

### 6.3 禁止

| ❌ | ✅ |
|----|----|
| 把常量塞进类里当枚举用 | 用 `StrEnum` 或 `Final` |
| `Enum`（不带 Str）直接 JSON 序列化 | 用 `StrEnum` 或 `use_enum_values=True` |
| 用魔法数字 | 用枚举 + 名称 |

---

## 8. Protocol vs ABC

### 8.1 决策

| 场景 | 选择 |
|------|------|
| 多类要 duck typing，不强制继承 | **Protocol**（默认优先） |
| 需要强制子类实现（防止漏方法） | **abc.ABC** + `@abstractmethod` |
| 需要模板方法模式（基类持有流程） | **abc.ABC** |
| 仅做类型提示，无运行时约束 | **Protocol** |

### 8.2 Protocol 命名

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class LLMClient(Protocol):
    """LLM 客户端的协议接口。"""

    async def chat(self, messages: list[dict]) -> str: ...
    async def stream(self, messages: list[dict]): ...
```

- 不强制 `IFoo` 前缀（PEP 544 风格），但项目内可统一加 `I` 前缀作风格选择
- 行为由调用方保证（结构子类型）

### 8.3 ABC 命名

```python
from abc import ABC, abstractmethod

class AbstractRetriever(ABC):
    """检索器抽象基类。"""

    @abstractmethod
    async def retrieve(self, query: str) -> list[str]: ...
```

- 类名加 `Abstract` 前缀（或项目约定 `Base` 前缀）
- 子类必须实现所有 `@abstractmethod` 才能实例化

---

## 9. 魔术方法（Dunder）

### 9.1 必须实现 / 自动生成的

| 方法 | 何时 | 谁生成 |
|------|------|--------|
| `__repr__` | 所有类（开发期调试必备） | `@dataclass` / `BaseModel` 自动 |
| `__str__` | 用户面向输出时 | 手写 |
| `__eq__` / `__hash__` | 值对象 | `@dataclass(frozen=True)` 自动；Pydantic 自动 |
| `__lt__` 等比较 | 值对象排序 | `@dataclass(order=True)` 自动 |
| `__init__` | 所有类 | 自动（dataclass / Pydantic） |
| `__iter__` | 类集合语义（"可迭代对象"） | 手写 |

### 9.2 默认不实现

| 方法 | 原因 |
|------|------|
| `__getattr__` | 极易破坏 IDE / Pickle / 静态分析，**禁止**随意使用 |
| `__getattribute__` | 同上 |
| `__del__` | GC 时机不可靠，资源释放用 `__enter__/__exit__` |
| `__copy__` / `__deepcopy__` | 默认实现够用，特殊场景才重写 |

### 9.3 Pydantic / dataclass 自动生成

- `__init__`、`__repr__`、`__eq__`：自动
- `__hash__`：仅在 `frozen=True` 时自动
- 字段顺序与定义顺序一致
- 需要自定义 `__repr__` 时必须 `__repr_args__` 或显式覆盖

---

## 10. DTO / 值对象 / 实体 三分法

| 类型 | 用途 | 实现 | 关键属性 |
|------|------|------|---------|
| **DTO** | 跨层数据传输（API ↔ 业务 ↔ 持久） | `@dataclass(frozen=True, slots=True)` | 不可变、无 id、纯数据 |
| **值对象（VO）** | 领域概念，无生命周期 | `@dataclass(frozen=True, slots=True, eq=True)` | 值相等、可哈希、不可变 |
| **实体（Entity）** | 有 id、有生命周期、可变状态 | 普通类 / `@dataclass` | 有 id、`__eq__` 基于 id、状态可变 |

```python
# DTO
@dataclass(frozen=True, slots=True)
class UserDTO:
    name: str
    email: str

# 值对象（值相等）
@dataclass(frozen=True, slots=True)
class Money:
    amount_cents: int
    currency: str
    # amount=100 USD == amount=100 USD

# 实体（有 id，可变）
@dataclass(slots=True)
class User:
    id: str            # 身份
    name: str
    email: str
    # User('u1', ...) == User('u1', ...) 基于 id
```

**强制：**

- 默认写**值对象**（不可变）而不是实体
- 实体放在持久层 + 业务层交界，DTO 放跨层

---

## 11. 序列化规则

### 11.1 内部序列化

```python
@dataclass(frozen=True, slots=True)
class ToolResult:
    name: str
    output: str

# → JSON
import json
json.dumps(asdict(result), ensure_ascii=False)
```

### 11.2 Pydantic 序列化

```python
# 默认 snake_case
doc.model_dump()
# {'document_id': '...', 'created_at': '...'}

# camelCase（对外 API）
doc.model_dump(by_alias=True)

# JSON 字符串
doc.model_dump_json(by_alias=True, indent=None)   # 紧凑
doc.model_dump_json(indent=2)                      # 调试用

# 排除 None
doc.model_dump(exclude_none=True)
```

### 11.3 禁止

| ❌ | ✅ |
|----|----|
| `__repr__` 里加可变对象引用 | 用 `repr=False` 或 repr 协议 |
| 序列化时混入 Python 私有 `_x` | 显式 `exclude={"_x"}` |
| 默认 `ensure_ascii=True` | `ensure_ascii=False`（保留中文） |
| 输出原始 `datetime` | 统一 ISO 8601 字符串 |

---

## 12. 速查清单

写一个新数据类前问自己：

1. **数据来自哪里？**
   - 外部 / 配置 → Pydantic `BaseModel`
   - 内部 → `@dataclass(frozen=True, slots=True)`
2. **是枚举吗？** → `StrEnum`
3. **有行为吗？**
   - 多类共享接口 → `Protocol`（默认）或 `ABC`
   - 单个服务类 → 普通类
4. **字段命名**
   - snake_case ✅
   - bool 加 `is_/has_` 前缀 ✅
   - 单位进名 ✅
   - 外部 API 用 alias 转换 camelCase ✅
5. **不可变优先**（除非是实体）✅
6. **每个字段 `description`**（Pydantic）✅
8. **不要重写自动生成的方法** ✅

---

## 13. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-09-24 | 初版：字段命名（单位进名、序列化别名）、对象选型、Pydantic/dataclass/Enum/Protocol/ABC 编写规则、魔术方法、DTO/VO/Entity 三分法、序列化 |