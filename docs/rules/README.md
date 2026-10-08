# Rules

项目级规则与约定。所有成员（包括 Claude）在改动代码前都应遵守这里的约定。

## 目录内容

| 文件 | 用途 |
|------|------|
| [`project-rules.md`](./project-rules.md) | 项目基本规则（环境、依赖、目录、Git） |
| [`commit-conventions.md`](./commit-conventions.md) | Git 提交规范（Conventional Commits + 中文） |

## 约定分类

| 类别 | 文件 |
|------|------|
| 项目基本规则 | [`project-rules.md`](./project-rules.md) |
| 提交规范 | [`commit-conventions.md`](./commit-conventions.md) |
| 编码规范 | 详见 [`docs/design/coding-style.md`](../design/coding-style.md) |
| 测试规范 | 详见 [`docs/design/architecture.md` §12](../design/architecture.md) |

## Git 模板

仓库根目录的 `.gitmessage` 是 `git commit` 默认模板：

```bash
git config commit.template .gitmessage
```

配好后每次 `git commit` 自动加载中文提示 + 类型清单。

## 提交校验

```bash
uv tool install pre-commit
pre-commit install --hook-type commit-msg
```

启用后 `commitlint` 自动拒绝不合规的 commit 信息。详见 [`commit-conventions.md` §9](./commit-conventions.md)。