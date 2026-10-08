# Git 提交规范

> 日期：2026-09-24
> 适用范围：本仓库所有 Git 提交。
> 风格：基于 [Conventional Commits](https://www.conventionalcommits.org/)，标题与正文使用中文。

---

## 1. 提交信息格式

```
<类型>[(作用域)]: <中文标题>

[可选正文：详细说明]

[可选页脚：BREAKING CHANGE / Closes #123 / Refs #456]
```

### 1.1 示例

```bash
# 单行（小型改动）
git commit -m "fix(wiki): 修复空 obj_token 导致 FeishuNotFoundError 的问题"

# 多行（带正文与页脚）
git commit -m "feat(lark_cli): 新增 Wiki + Docx 工具封装

- 用 subprocess 调 lark-cli，替代原 lark-oapi SDK
- 保留 LarkCli / WikiCliService / DocCliService 接口
- 异常映射：404 → FeishuNotFoundError 等

Closes #12"
```

---

## 2. 类型（Type）

| 类型 | 用途 | 标题示例 |
|------|------|---------|
| `feat` | 新增功能 | `feat(lark_cli): 新增 Wiki + Docx 工具封装` |
| `fix` | 修复 bug | `fix(config): 修复 requires-python 默认值与 uv sync 冲突` |
| `docs` | 仅文档变更 | `docs(design): 补充 data-modeling §3 Pydantic 编写规则` |
| `refactor` | 重构（既不修 bug 也不加功能） | `refactor(feishu): 把 utils.feishu 子包拍平到顶层` |
| `test` | 添加 / 修改测试 | `test(wiki): 补充 WikiCliService 异常映射单元测试` |
| `chore` | 工具 / 构建 / 依赖 / 杂项 | `chore(deps): 升级 langchain-openai 到 1.6.6` |
| `perf` | 性能优化 | `perf(doc): 缓存 Docx blocks，减少重复调用` |
| `style` | 仅格式（空格 / 引号 / 缩进） | `style: ruff format 全量重写` |
| `ci` | CI 配置 | `ci(github): 加 ruff check 到 actions` |
| `revert` | 回滚提交 | `revert: 回退 feat(lark_cli) 的破坏性改动` |

---

## 3. 作用域（Scope，可选）

作用域放在括号里，写**模块名 / 子包名**：

```
feat(lark_cli): ...        # 飞书 CLI 适配层
fix(wiki): ...              # Wiki service
refactor(tools): ...        # agent tools 层
chore(deps): ...            # 依赖
docs(design): ...           # design 文档
```

**约定作用域清单**（按本项目结构）：

| 作用域 | 含义 |
|--------|------|
| `core` | 主智能体编排（`src/core/`） |
| `core.agents` | sub-agent 注册（目录名 `subagent`） |
| `feishu` | 飞书包整体 |
| `lark_cli` | lark-cli subprocess 适配层 |
| `wiki` | Wiki service |
| `doc` | Docx service |
| `tools` | agent tools |
| `config` | 配置加载 |
| `llm` | LLM 客户端 |
| `deps` | 依赖变更 |
| `ci` | CI / hooks |
| `docs` | 文档（缺省作用域） |
| `format` / `lint` | 仅格式化 / 仅 lint |

无作用域时直接写 `feat: ...`。

---

## 4. 标题（Subject）

| 项 | 规则 |
|----|------|
| **语言** | **中文**（项目主要语言） |
| **长度** | ≤ 50 字符；超长拆 `scope` 或移正文 |
| **时态** | 用「动名词」开头：`新增` / `修复` / `调整` / `移除` / `重构` |
| **结尾** | **不加句号** |
| **首字母** | 不强制大写 |

✅ 推荐：
```
feat(lark_cli): 新增 Wiki + Docx 工具封装
fix(wiki): 解析节点失败时抛出 FeishuNotFoundError
docs(design): 补充字段命名 §1.2 单位进名规则
```

❌ 避免：
```
update code              # 没类型，没作用域，英文
feat(lark_cli): 新增 Wiki + Docx 工具封装。  # 加句号
fix bug                  # 描述太泛
Feat(lark_cli): 新增    # 类型大写
```

---

## 5. 正文（Body，可选）

| 项 | 规则 |
|----|------|
| **何时写** | 改动跨多文件 / 行为反直觉 / 修复 bug |
| **分隔** | 标题与正文之间空一行 |
| **行宽** | 72 字符 |
| **结构** | 列表（`- ...`）描述要点 |
| **动机** | 第一行写「为什么改」而不是「改了什么」 |
| **对比** | 关键代码片段可用三引号围栏 |

```bash
feat(lark_cli): 新增 Wiki + Docx 工具封装

为什么：lark-oapi SDK 维护成本高，鉴权流不灵活。
方案：调 lark-cli subprocess，复用其 OAuth 状态。

- 新增 feishu/utils/lark_cli/{client,wiki,doc}.py
- LarkCli 自动映射异常：404 → FeishuNotFoundError
- 旧 FeishuClient 别名保留，向后兼容
- tools 层零改动（接口保持一致）

BREAKING CHANGE: FeishuClient 构造参数从 FeishuConfig 改为 LarkCli。
```

---

## 6. 页脚（Footer，可选）

| 用途 | 语法 |
|------|------|
| 关闭 issue | `Closes #123` / `Fixes #456` |
| 关联 issue（不关闭） | `Refs #789` |
| 破坏性变更 | `BREAKING CHANGE: <说明>` |
| 共同作者 | `Co-authored-by: Name <email>` |

---

## 7. 分支命名

```
main                       # 主分支，受保护
feat/<scope>-<slug>        # 新功能，如 feat/lark-cli-calendar
fix/<scope>-<slug>         # 修复，如 fix/wiki-empty-token
chore/<slug>               # 杂项，如 chore/upgrade-deps
docs/<slug>                # 文档，如 docs/commit-conventions
refactor/<scope>-<slug>    # 重构
```

slug 用 kebab-case、英文短词。

---

## 8. 工作流

1. **feat / fix**：从 `main` 拉分支 → 提交 → push → 提 PR
2. **docs / chore / style / refactor（低风险）**：可直接提交到 `main`（小团队）或走 PR（看团队规则）
3. PR 标题与 commit 标题同格式
4. Squash merge：合并后保留所有 commits 详情；rebase merge：保证线性历史

---

## 9. 工具支持（CI 强制）

### 9.1 `.gitmessage` 模板

仓库根目录的 `.gitmessage` 自动作为 `git commit` 的模板：

```bash
git config commit.template .gitmessage
```

启用后每次 `git commit` 自动加载中文提示 + 类型清单（见仓库根目录的 `.gitmessage`）。

### 9.2 pre-commit + commitlint（**推荐**）

项目已配置 `.pre-commit-config.yaml` + `commitlint.config.cjs`，启用的 commit-msg hook 会拒绝不合规提交。

**一次性安装**：

```bash
# 1. 装 pre-commit（与 uv 隔离，不污染项目依赖）
uv tool install pre-commit

# 2. 启用 hooks（写入 .git/hooks/）
pre-commit install
# 装完后 commit-msg hook 自动生效
```

**手动校验所有文件**：

```bash
pre-commit run --all-files
```

**手动校验最新一次 commit**（调试用）：

```bash
pre-commit run commitlint --hook-stage commit-msg --commit-msg .git/COMMIT_EDITMSG
```

**规则摘要**（见 `commitlint.config.cjs`）：

| 规则 | 说明 |
|------|------|
| `header-max-length` | 标题 ≤ 100 字符 |
| `type-enum` | 类型必须 ∈ {feat, fix, docs, refactor, test, chore, perf, style, ci, revert} |
| `subject-empty` | 标题不能为空 |
| `subject-full-stop` | 标题**不**能以 `.` 结尾 |
| `scope-empty` | 允许无 scope |
| `header-pattern` | 必须匹配 `<type>[(<scope>)]: <subject>` |

### 9.3 备选方案：纯 Node 工具链（commitlint + husky）

如团队偏好 Node 工具链：

```bash
# 1. 初始化 package.json
npm init -y
npm i -D @commitlint/cli @commitlint/config-conventional husky

# 2. 启用 husky
npx husky install
echo "import '@commitlint/cli'" > .husky/commit-msg

# 3. 在 .husky/commit-msg 里加
npx --no -- commitlint --edit "$1"
```

配置 `commitlint.config.cjs`（项目已提供）。

**两种方案二选一**：pre-commit（推荐，Python 原生）vs husky（备选，Node 工具链）。

### 9.4 release-please（自动生成 changelog）

按 conventional commits 自动生成 CHANGELOG.md 与 GitHub release：

```yaml
# release-please-config.json（待加）
{
  "packages": {".": {"releaseType": "python"}},
  "bump-minor-pre-major": false,
  "bump-patch-for-minor-pre-major": false
}
```

触发 `.github/workflows/release-please.yml` 后，每次 push 到 main 自动创建 PR 升版本号。

---

## 10. 启用检查清单

新克隆项目后，开发者应：

```bash
uv sync --extra dev         # 装 ruff / mypy / pytest
uv tool install pre-commit   # 装 pre-commit
pre-commit install           # 启用 git hooks
git config commit.template .gitmessage  # 可选：commit 模板
```

不启用 hook 不会影响 push，但 CI（若配置）会拒绝不合规 commit。

---

## 11. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-09-24 | 初版：基于 Conventional Commits，中文标题/正文 |
| 2026-09-24 | 增 §9：pre-commit + commitlint 配置说明 + 启用检查清单 |