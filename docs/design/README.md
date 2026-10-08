# Project Design

整个项目的设计规约。涵盖 Python 语法规则、命名规范、文件路径、架构设计。

## 目录内容

| 文件 | 用途 |
|------|------|
| [`coding-style.md`](./coding-style.md) | 语法规则、命名规范、类型提示、Docstring、Import 顺序、错误处理、日志 |
| [`project-layout.md`](./project-layout.md) | 目录结构、文件路径、`src/` layout、`pyproject.toml` 布局 |
| [`architecture.md`](./architecture.md) | 架构分层、依赖方向、模块化、配置、数据模型、可观测性 |
| [`core-architecture.md`](./core-architecture.md) | 当前 core 调用关系、架构图与精简讨论方案 |
| [`data-modeling.md`](./data-modeling.md) | 字段命名（单位进名、序列化别名）、对象选型、Pydantic / dataclass / Enum / Protocol / ABC 编写规则、DTO/VO/Entity 三分法 |

## 与其他文档的关系

| 文档 | 范围 |
|------|------|
| `docs/design/` | **硬性规约** —— 写代码必须遵守 |
| `docs/rules/` | 项目级约定（环境、Git、Claude 协作）|
| `docs/notes/` | 探索性笔记与初始化记录 |
| `docs/feishu/` | 外部对接设计稿 |

## 主要参考来源

- [PEP 8 – Style Guide for Python Code](https://peps.python.org/pep-0008/)
- [PEP 257 – Docstring Conventions](https://peps.python.org/pep-0257/)
- [PEP 484 – Type Hints](https://peps.python.org/pep-0484/)
- [PEP 604 – Allow writing union types as X | Y](https://peps.python.org/pep-0604/)
- [PEP 621 – Project Metadata in pyproject.toml](https://peps.python.org/pep-0621/)
- [Python Packaging User Guide – src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
